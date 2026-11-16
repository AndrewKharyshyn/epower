#!/usr/bin/env python3
"""M704 (spec analyses/M703_spec.md Rev 1 item 1): register the archived manufacturer source documents. Read-only: hashes the files (sha256, size), records the page count, the PDF metadata, the text-layer
status and, for every page cited in analyses/M704_transcription_pass1.json, the sha256 of the rendered page image (pymupdf, 120 dpi PNG; the library version is recorded because the hash depends on it).
The PDFs live OUTSIDE the repository (reference_downloads/nissan_technical_review_89_90/); the repository holds only this register. No manufacturer number is written by this tool.
Usage: python tools/oem_source_register.py OUT.json"""
import hashlib, json, os, sys, datetime
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DIR = os.path.abspath(os.path.join(ROOT, "..", "..", "reference_downloads", "nissan_technical_review_89_90"))
SOURCES = {
    "TR89": {"file": "NISSAN_TECHINICAL_REVIEW_89_En_ALL.pdf", "url": "https://www.nissan-global.com/EN/TECHNICALREVIEW/PDF/NISSAN_TECHINICAL_REVIEW_89_En_ALL.pdf", "serverLastModified": "Wed, 01 Jul 2026 03:55:21 GMT", "serverContentLength": 40977266},
    "TR90": {"file": "NISSAN_TECHINICAL_REVIEW_90_En_SP1.pdf", "url": "https://www.nissan-global.com/EN/TECHNICALREVIEW/PDF/TOPIC/NISSAN_TECHINICAL_REVIEW_90_En_SP1.pdf", "serverLastModified": "Fri, 31 Jul 2026 13:32:14 GMT", "serverContentLength": 37055898},
}


def main(out):
    import pymupdf
    p1 = json.load(open(os.path.join(ROOT, "analyses", "M704_transcription_pass1.json"), encoding="utf-8"))
    cited = {}
    for s in p1["statements"]:
        cited.setdefault(s["doc"], set()).add(s["pdfPage"])
    res = {"spec": "analyses/M703_spec.md Rev 1 item 1", "registeredAt": datetime.datetime.now(datetime.timezone.utc).isoformat(), "ownerInstruction": "URLs supplied by the owner in chat on 2026-11-16 (download approved for these two documents)",
           "storedOutsideRepository": "reference_downloads/nissan_technical_review_89_90/", "pymupdfVersion": pymupdf.__version__, "documents": {}}
    for k, v in SOURCES.items():
        path = os.path.join(DIR, v["file"])
        b = open(path, "rb").read()
        d = pymupdf.open(path)
        txt = [i for i, p in enumerate(d) if len(p.get_text().strip()) > 200]
        rec = {**v, "sizeBytes": len(b), "sizeMatchesServer": len(b) == v["serverContentLength"], "sha256": hashlib.sha256(b).hexdigest(), "pages": d.page_count, "pagesWithTextLayer": len(txt),
               "pdfMetadata": {a: c for a, c in (d.metadata or {}).items() if c and a in ("format", "creator", "producer", "creationDate", "modDate", "title")}, "language": "English (original, not a translation)",
               "citedPageImageSha256": {}}
        for pg in sorted(cited.get(k, [])):
            png = d[pg - 1].get_pixmap(dpi=120).tobytes("png")
            rec["citedPageImageSha256"][str(pg)] = hashlib.sha256(png).hexdigest()
        res["documents"][k] = rec
    res["scriptSha256"] = hashlib.sha256(open(__file__, "rb").read()).hexdigest()
    json.dump(res, open(out, "w", encoding="utf-8"), indent=1)
    print(json.dumps({k: {"sizeBytes": v["sizeBytes"], "sizeMatchesServer": v["sizeMatchesServer"], "sha256": v["sha256"][:16], "pages": v["pages"], "citedPages": len(v["citedPageImageSha256"])} for k, v in res["documents"].items()}))


if __name__ == "__main__":
    main(sys.argv[1])
