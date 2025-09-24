#!/usr/bin/env python3
"""
SageMaker pipeline script to process DTIS taxonomy data.
Reads CSV from S3, enriches with WoRMS data, and stores in MongoDB.
"""

import argparse
import csv
import io
import logging
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List, Optional, Tuple

import boto3
import pymongo
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logging.basicConfig(stream=sys.stdout, level=logging.INFO)
_logger = logging.getLogger(__name__)

def make_session(timeout: int = 15) -> requests.Session:
    """Create requests session with retry logic."""
    retry = Retry(
        total=5,
        backoff_factor=0.5,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=["GET"],
    )
    adapter = HTTPAdapter(max_retries=retry)
    session = requests.Session()
    session.mount("https://", adapter)
    session.request_timeout = timeout
    return session


def get_worms_data(session: requests.Session, aphia_id: int) -> Dict:
    """Fetch complete WoRMS data for AphiaID."""
    url = f"https://www.marinespecies.org/rest/AphiaRecordByAphiaID/{aphia_id}"
    try:
        resp = session.get(url, timeout=session.request_timeout)
        if resp.status_code == 200:
            return resp.json() or {}
    except Exception:
        pass
    return {}


def get_vernacular_names(session: requests.Session, aphia_id: int) -> List[str]:
    """Fetch English vernacular names for AphiaID."""
    url = f"https://www.marinespecies.org/rest/AphiaVernacularsByAphiaID/{aphia_id}"
    try:
        resp = session.get(url, timeout=session.request_timeout)
        if resp.status_code == 200:
            vernaculars = resp.json() or []
            return [v["vernacular"] for v in vernaculars if v.get("language_code") == "eng"]
    except Exception:
        pass
    return []


def get_environment(data: Dict) -> str:
    """Extract environment from WoRMS flags."""
    envs = []
    if data.get("isMarine") == 1:
        envs.append("marine")
    if data.get("isBrackish") == 1:
        envs.append("brackish")
    if data.get("isFreshwater") == 1:
        envs.append("fresh")
    if data.get("isTerrestrial") == 1:
        envs.append("terrestrial")
    return ", ".join(envs)


def read_csv_from_s3(bucket: str, key: str) -> List[Dict[str, str]]:
    """Read CSV file from S3."""
    s3 = boto3.client('s3')
    obj = s3.get_object(Bucket=bucket, Key=key)
    content = obj['Body'].read().decode('utf-8')
    
    reader = csv.DictReader(io.StringIO(content))
    return [{k.strip(): v.strip() if v else "" for k, v in row.items()} for row in reader]


def process_rows(rows: List[Dict[str, str]], workers: int = 5) -> List[Dict]:
    """Process CSV rows and enrich with WoRMS data."""
    session = make_session()
    
    # Build lookup maps
    id_to_row = {row["id"]: row for row in rows if row.get("id")}
    
    # Collect unique AphiaIDs
    aphia_ids = []
    for row in rows:
        source_id = row.get("source_id", "").strip()
        if source_id:
            try:
                aphia_ids.append(int(source_id))
            except ValueError:
                pass
    
    # Fetch WoRMS data in parallel
    worms_cache = {}
    vernacular_cache = {}
    
    with ThreadPoolExecutor(max_workers=workers) as executor:
        # Fetch WoRMS records
        worms_futures = {executor.submit(get_worms_data, session, aid): aid for aid in set(aphia_ids)}
        for future in as_completed(worms_futures):
            aid = worms_futures[future]
            try:
                worms_cache[aid] = future.result()
            except Exception:
                worms_cache[aid] = {}
        
        # Fetch vernacular names
        vernacular_futures = {executor.submit(get_vernacular_names, session, aid): aid for aid in set(aphia_ids)}
        for future in as_completed(vernacular_futures):
            aid = vernacular_futures[future]
            try:
                vernacular_cache[aid] = future.result()
            except Exception:
                vernacular_cache[aid] = []
    
    # Process each row
    documents = []
    for row in rows:
        source_id = row.get("source_id", "").strip()
        
        if source_id:
            try:
                aphia_id = int(source_id)
                worms_data = worms_cache.get(aphia_id, {})
                common_names = vernacular_cache.get(aphia_id, [])
                
                doc = {
                    "name": row.get("name", ""),
                    "rank": worms_data.get("rank", ""),
                    "aphia_id": str(worms_data.get("valid_AphiaID", "")),
                    "parent_name": "",  # Will be filled later
                    "parent_aphia_id": "",  # Will be filled later
                    "common_names": common_names,
                    "scientific_name": worms_data.get("valid_name", ""),
                    "status": worms_data.get("status", ""),
                    "environment": get_environment(worms_data),
                    "extinct": str(worms_data.get("isExtinct", "")),
                    "kingdom": worms_data.get("kingdom", ""),
                    "phylum": worms_data.get("phylum", ""),
                    "class": worms_data.get("class", ""),
                    "order": worms_data.get("order", ""),
                    "family": worms_data.get("family", ""),
                    "genus": worms_data.get("genus", ""),
                    "valid_authority": worms_data.get("valid_authority", ""),
                    "modified": worms_data.get("modified", ""),
                    "_original_id": row.get("id", ""),
                    "_parent_id": row.get("parent_id", "")
                }
            except ValueError:
                # Invalid source_id
                doc = create_arbitrary_doc(row)
        else:
            # No source_id
            doc = create_arbitrary_doc(row)
        
        documents.append(doc)
    
    # Fill parent information
    fill_parent_info(documents, id_to_row, worms_cache)
    
    return documents


def create_arbitrary_doc(row: Dict[str, str]) -> Dict:
    """Create document for rows without source_id."""
    return {
        "name": row.get("name", ""),
        "rank": "Arbitrary",
        "aphia_id": "",
        "parent_name": "",
        "parent_aphia_id": "",
        "common_names": [],
        "scientific_name": row.get("name", ""),
        "status": "",
        "environment": "",
        "extinct": "",
        "kingdom": "",
        "phylum": "",
        "class": "",
        "order": "",
        "family": "",
        "genus": "",
        "valid_authority": "",
        "modified": "",
        "_original_id": row.get("id", ""),
        "_parent_id": row.get("parent_id", "")
    }


def fill_parent_info(documents: List[Dict], id_to_row: Dict, worms_cache: Dict):
    """Fill parent_name and parent_aphia_id after all WoRMS data is fetched."""
    id_to_doc = {doc["_original_id"]: doc for doc in documents}
    
    for doc in documents:
        parent_id = doc.get("_parent_id", "").strip()
        if parent_id and parent_id in id_to_doc:
            parent_doc = id_to_doc[parent_id]
            doc["parent_name"] = parent_doc.get("scientific_name", "")
            doc["parent_aphia_id"] = parent_doc.get("aphia_id", "")
        
        # Clean up temporary fields
        doc.pop("_original_id", None)
        doc.pop("_parent_id", None)


def insert_to_mongodb(documents: List[Dict], mongo_uri: str, db_name: str, collection_name: str):
    """Insert documents to MongoDB."""
    client = pymongo.MongoClient(mongo_uri)
    db = client[db_name]
    collection = db[collection_name]
    
    # Clear existing data
    collection.delete_many({})
    
    # Insert new documents
    if documents:
        collection.insert_many(documents)
    
    client.close()


def main():
    parser = argparse.ArgumentParser(description="Process DTIS taxonomy data")
    parser.add_argument("--s3bucket", required=True, help="S3 bucket name")
    parser.add_argument("--s3key", required=True, help="S3 key for CSV file")
    parser.add_argument("--mongo_uri", required=True, help="MongoDB connection URI")
    parser.add_argument("--mongo_db", default="dtis-data", help="MongoDB database name")
    parser.add_argument("--mongo_collection", default="dtis_taxonomy", help="MongoDB collection name")
    parser.add_argument("--workers", type=int, default=5, help="Number of worker threads")
    
    args, _ = parser.parse_known_args()

    _logger.info(f"Reading CSV from s3://{args.s3bucket}/{args.s3key}")
    rows = read_csv_from_s3(args.s3bucket, args.s3key)
    _logger.info(f"Processing {len(rows)} rows")

    documents = process_rows(rows, args.workers)
    _logger.info(f"Generated {len(documents)} documents")

    _logger.info(f"Inserting to MongoDB: {args.mongo_db}.{args.mongo_collection}")
    insert_to_mongodb(documents, args.mongo_uri, args.mongo_db, args.mongo_collection)
    _logger.info("Processing complete")


if __name__ == "__main__":
    main()