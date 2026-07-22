"""DAG: SEC EDGAR filing sync (dag_sec_edgar).

Uses EdgarTools (free, no API key -- SEC requires a real identifying
User-Agent per its fair-access policy, set via EDGAR_IDENTITY).
Ingests company records (business) and filing records (government_filing)
for a configured list of tickers. Officer/insider names that appear in
Form 4 filings are NOT extracted into their own records here -- see
ROADMAP.md: no individual profiling. Only the company and the filing
itself (form type, date, accession number, URL) are stored.
"""

from __future__ import annotations

import os
import sys
from datetime import datetime

import pendulum

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from airflow.sdk import dag, task

DEFAULT_TICKERS = ["AAPL", "MSFT"]
DEFAULT_FORMS = ["10-K", "10-Q", "8-K"]
FILINGS_PER_TICKER = 5


@dag(
    dag_id="sec_edgar_ingestion",
    description="Syncs SEC EDGAR company + filing records into research_entities via EdgarTools.",
    schedule="@daily",
    start_date=pendulum.datetime(2026, 1, 1, tz="UTC"),
    catchup=False,
    tags=["ingestion", "sec-edgar", "public-records"],
)
def sec_edgar_ingestion_dag():
    @task
    def fetch_filings() -> list[dict]:
        from edgar import Company, set_identity
        from airflow.sdk import Variable

        from common.pii_scrub import scrub_record

        identity = os.environ.get("EDGAR_IDENTITY", "")
        if not identity:
            # EdgarTools refuses to run without an identity -- SEC blocks
            # unidentified traffic. Fail soft rather than crash the DAG.
            return []
        set_identity(identity)

        try:
            tickers = Variable.get("sec_edgar_tickers", deserialize_json=True)
        except Exception:
            tickers = DEFAULT_TICKERS

        records: list[dict] = []
        for ticker in tickers:
            try:
                company = Company(ticker)
            except Exception:
                continue

            records.append(
                scrub_record(
                    {
                        "name": company.name,
                        "entity_type": "business",
                        "source": "sec_edgar",
                        "license": "SEC EDGAR -- public domain, no copyright restriction",
                        "metadata": {
                            "cik": company.cik,
                            "ticker": ticker,
                            "retrieved_at": datetime.utcnow().isoformat(),
                        },
                    }
                )
            )

            filings = company.get_filings(form=DEFAULT_FORMS).head(FILINGS_PER_TICKER)
            for f in filings:
                records.append(
                    scrub_record(
                        {
                            "name": f"{company.name} {f.form} ({f.filing_date})",
                            "entity_type": "government_filing",
                            "source": "sec_edgar",
                            "license": "SEC EDGAR -- public domain, no copyright restriction",
                            "metadata": {
                                "cik": company.cik,
                                "ticker": ticker,
                                "form": f.form,
                                "accession_no": f.accession_no,
                                "filing_date": str(f.filing_date),
                                "url": f.filing_url,
                                "retrieved_at": datetime.utcnow().isoformat(),
                            },
                        }
                    )
                )

        return records

    @task
    def load_records(records: list[dict]) -> int:
        from common.db import upsert_entities

        return upsert_entities(records)

    load_records(fetch_filings())


sec_edgar_ingestion_dag()
