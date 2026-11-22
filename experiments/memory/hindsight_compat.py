"""Candidate compatibility adapter; NOT enabled in the active service.

Hindsight1.2.0 calls dateparser's private search_parse API and unpacks pairs.
The installed dateparser returns (text, datetime, period) triples. Preserve the
native scoring/period logic and normalize that transport shape. Restrict locale
work to English, as the owner selected. Requires separate qualification before
any runtime change; never edits the installed package or old evidence.
"""
from datetime import datetime


def normalize_date_results(results):
    if results is None:return None
    normalized=[]
    for result in results:
        if not isinstance(result,(tuple,list)) or len(result) not in (2,3):
            raise ValueError('Unexpected dateparser result shape')
        text,date=result[:2]
        if not isinstance(text,str) or not isinstance(date,datetime):
            raise ValueError('Unexpected dateparser match types')
        normalized.append((text,date))
    return normalized or None


def english_query_analyzer():
    from hindsight_api.engine.query_analyzer import DateparserQueryAnalyzer
    class CompatibleAnalyzer(DateparserQueryAnalyzer):
        def __init__(self):super().__init__(languages=['en'])
        def _find_dates(self,query,settings=None):
            return normalize_date_results(super()._find_dates(query,settings=settings))
    return CompatibleAnalyzer()
