from pydantic import BaseModel, validator
from typing import ClassVar, Any, Optional, Tuple, List, Dict, Generator, Union, NamedTuple
from ncbiutils.types import HttpMethodEnum, DbEnum, RetModeEnum, RetTypeEnum
from ncbiutils.http import safe_requests
from ncbiutils.pubmedxmlparser import Citation, PubmedXmlParser


class Chunk(NamedTuple):
    """Article records are delivered in multiple Chunks"""

    error: Optional[Exception]
    records: Optional[List[Citation]]
    ids: Optional[List[str]]


class Eutil(BaseModel):
    """
    A base class for other NCBI E-Utilities

    Class attributes
    ----------
    base_url : str
        Base URL for the various NCBI E-Utilities
    retmax_limit : int
        Maximum number of records that can be returned

    Attributes
    ----------
    retstart : int
        Index before the first record to return (default 0)
    retmax : int
        Maximum number of records to return (default 10000)
    api_key : str
        Key for NCBI E-Utilities

    Methods
    ----------
    request(url: str, **opts)
        Make request with appropriate body form parameters

    """

    base_url: ClassVar[str] = 'https://eutils.ncbi.nlm.nih.gov/entrez/eutils/'
    retmax_limit: ClassVar[int] = 10000

    retstart: int = 0
    retmax: int = retmax_limit
    api_key: Optional[str] = None

    @validator('retmax')
    def retmax_is_nonneg_lt_limit(cls, v):
        if v < 0 or v > cls.retmax_limit:
            raise ValueError(f'Must be positive number less than {cls.retmax_limit}')
        return v

    def request(self, url: str, **opts) -> Tuple[Optional[Exception], Any]:
        """Call one of the NCBI E-Utilities and return (error, requests.Response)"""
        params: Dict[str, Union[str, int]] = {'retstart': self.retstart, 'retmax': self.retmax}
        params.update(opts)
        if self.api_key:
            params.update({'api_key': self.api_key})
        err, response = safe_requests(url, method=HttpMethodEnum.POST, files=params, stream=True)
        return err, response


class Efetch(Eutil):
    """
    A class tailored for the EFETCH E-Utility

    Class attributes
    ----------
    efetch_url : str
        The E-Utilities URL for EFETCH

     Methods
    ----------
    request(db: DbEnum, id: str, **opts)
        Make request to EFETCH URL with constrained body form parameters

    """

    url: ClassVar[str] = f'{Eutil.base_url}efetch.fcgi'

    def _fetch(self, db: DbEnum, id: str, **opts) -> Tuple[Optional[Exception], Any]:
        """Call EFETCH E-Utility for the given id and db"""
        params: Dict[str, Union[str, int]] = {'db': db, 'id': id}
        params.update(opts)
        err, response = self.request(self.url, **params)
        return err, response


class PubMedFetch(Efetch):
    """
    A class that retrieves article information from PubMed

    Class attributes
    ----------
    db : DbEnum
        The pubmed database

    Methods
    -------
    fetch(uids: List[str])
        Retrieve text records given the list of uids

    """

    db: ClassVar[DbEnum] = DbEnum.pubmed

    retmode: RetModeEnum = RetModeEnum.xml
    rettype: Optional[RetTypeEnum]

    def fetch(self, ids: List[str]) -> Tuple[Optional[Exception], Any]:
        """Return id, and text (i.e. title + abstract) given a PubMed id"""
        id = ','.join(ids)
        params: Dict[str, Union[str, int, RetModeEnum, Optional[RetTypeEnum]]] = {
            'retmode': self.retmode,
            'rettype': self.rettype,
        }
        err, response = self._fetch(db=self.db, id=id, **params)
        return err, response

    def _parse_xml(self, data: bytes) -> List[Citation]:
        """Return a list of Citations given the server response"""
        parser = PubmedXmlParser()
        records = parser.parse(data)
        return list(records)

    def _parse_response(self, data: bytes) -> List[Citation]:
        """Delegate to an implementation or raise ValueError."""
        if self.retmode == RetModeEnum.xml and self.rettype is None:
            return self._parse_xml(data)
        else:
            raise ValueError(f'Unsupported retmode: {self.retmode}')

    def _chunks(self, lst: List[str], n: int) -> Generator[List[str], None, None]:
        """Yield successive n-sized chunks from lst."""
        for i in range(0, len(lst), n):
            yield lst[i : i + n]

    def get_citations(self, uids: List[str]) -> Generator[Chunk, None, None]:
        """Yields Chunk error, records (possibly empty) and PubMed uids"""
        for ids in self._chunks(uids, self.retmax):
            records = None
            error, response = self.fetch(ids)
            if not error and response:
                records = self._parse_response(response.content)
            yield Chunk(error, records, ids)
