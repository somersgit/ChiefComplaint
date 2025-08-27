import os, re, time, html
from typing import List, Dict
import requests
from bs4 import BeautifulSoup
from Bio import Entrez

# Configure Entrez (PubMed) - email required for polite access
Entrez.email = os.getenv("ENTREZ_EMAIL", "you@example.com")
Entrez.tool = os.getenv("ENTREZ_TOOL", "resident-attending-simulator")

TRUSTED_DOMAINS = [
    "nih.gov",
    "ncbi.nlm.nih.gov", # includes PubMed/PMC
    "cdc.gov",
    "who.int",
    "mayoclinic.org",
    "hopkinsmedicine.org"
]

class EvidenceFinder:
    def __init__(self):
        pass

    def find_evidence(self, diagnosis: str, recap_text: str, max_items: int = 5) -> List[Dict[str,str]]:
        items: List[Dict[str,str]] = []
        # 1) PubMed search focusing on diagnosis
        try:
            items.extend(self._pubmed_best(diagnosis, max_items=max_items))
        except Exception:
            pass

        # 2) If we still have room, try NIH/CDC/WHO/Mayo/JH generic lookups
        #    (best-effort, no API key; may not return much without a proper search API)
        if len(items) < max_items:
            try:
                items.extend(self._best_effort_web(diagnosis, remaining=max_items-len(items)))
            except Exception:
                pass

        # Deduplicate by URL
        seen = set()
        uniq = []
        for e in items:
            url = e.get("url")
            if url and url not in seen:
                uniq.append(e)
                seen.add(url)
        return uniq[:max_items]

    # --- PubMed utils ---
    def _pubmed_best(self, query: str, max_items: int = 5) -> List[Dict[str,str]]:
        term = f"{query} AND (review[pt] OR guideline[pt] OR systematic[sb]) AND english[lang]"
        handle = Entrez.esearch(db="pubmed", term=term, sort="relevance", retmax=str(max_items))
        record = Entrez.read(handle)
        handle.close()
        ids = record.get("IdList", [])
        if not ids:
            return []

        handle = Entrez.esummary(db="pubmed", id=",".join(ids))
        summary = Entrez.read(handle)
        handle.close()

        results = []
        for doc in summary:
            title = doc.get("Title", "PubMed result")
            # Try to use PMC link if available
            uid = doc.get("Id")
            url = f"https://pubmed.ncbi.nlm.nih.gov/{uid}/"
            results.append({"title": title, "url": url})
        return results

    # --- Very simple best-effort fetch for trusted domains (no API key) ---
    def _best_effort_web(self, query: str, remaining: int) -> List[Dict[str,str]]:
        results: List[Dict[str,str]] = []
        # We attempt a naive search via DuckDuckGo lite HTML endpoint (often works without keys).
        # If it fails, we simply return [].
        try:
            for domain in TRUSTED_DOMAINS:
                if remaining <= 0: break
                q = requests.utils.quote(f"site:{domain} {query}")
                url = f"https://duckduckgo.com/html/?q={q}"
                r = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
                if r.status_code != 200: 
                    continue
                soup = BeautifulSoup(r.text, "html.parser")
                for a in soup.select("a.result__a"):
                    title = a.get_text(strip=True)
                    href = a.get("href","")
                    if not href or not href.startswith("http"):
                        continue
                    results.append({"title": title, "url": href})
                    remaining -= 1
                    if remaining <= 0: break
        except Exception:
            pass
        return results
    #--------------------------------------
    def gather_evidence(self, topic: str, max_items: int = 6) -> List[Dict]:
        """
        Return up to max_items trusted items (PubMed/NIH/CDC/WHO/Mayo/JHM).
        Each item: {"title": str, "url": str}
        """
        results: List[Dict] = []
        if not topic:
            return results

        # 1) PubMed search (prefer fresh & relevant)
        try:
            handle = Entrez.esearch(db="pubmed", term=topic, sort="relevance", retmax=max_items)
            rec = Entrez.read(handle)
            ids = rec.get("IdList", [])[:max_items]
            if ids:
                # fetch titles + links from PubMed
                fetch = Entrez.efetch(db="pubmed", id=",".join(ids), rettype="docsum", retmode="xml")
                docs = Entrez.read(fetch)
                for doc in docs.get("DocSum", []):
                    pmid = ""
                    title = ""
                    for item in doc.get("Item", []):
                        if item.attributes.get("Name") == "Title":
                            title = item.title() if hasattr(item, "title") else str(item)
                        if item.attributes.get("Name") == "Id":
                            pmid = str(item)
                    if title or pmid:
                        results.append({"title": title or f"PubMed {pmid}", "url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/"})
                    if len(results) >= max_items:
                        break
        except Exception:
            pass

        remaining = max_items - len(results)
        if remaining <= 0:
            return results

        # 2) Domain-restricted web search for guidelines/overviews
        try:
            # very light-weight duckduckgo HTML scrape, already present in this file
            trusted = [
                "nih.gov", "ncbi.nlm.nih.gov", "cdc.gov", "who.int",
                "mayoclinic.org", "hopkinsmedicine.org"
            ]
            more = self.search_duckduckgo(topic, domains=trusted, limit=remaining)  # uses your existing helper
            for m in more:
                results.append({"title": m.get("title",""), "url": m.get("url","")})
                if len(results) >= max_items:
                    break
        except Exception:
            pass

        return results
