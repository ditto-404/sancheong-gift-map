"""Build data/merchants.js from the source spreadsheet and the geocode cache.

Usage (from the repo root):
    pip install openpyxl
    python scripts/build_data.py             # build data/merchants.js
    python scripts/build_data.py --queries   # write data/source/queries.json for geocode.mjs

Inputs
    data/source/*.xlsx   Sancheong gift certificate merchant list (one sheet)
    data/geocode.json    Coordinates and Kakao place ids, keyed by merchant number

Output
    data/merchants.js    window.MERCHANTS = {...}; loaded by index.html
"""
import glob
import json
import re
from pathlib import Path

import openpyxl

ROOT = Path(__file__).resolve().parent.parent

# Category groups shown as filter chips. Order here is the order on the page.
GROUPS = ["food", "cafe", "mart", "farm", "stay", "health", "beauty", "edu", "car", "leisure", "etc"]

# Kakao category prefix -> group. The first match wins, so keep specific rows on top.
KAKAO_RULES = [
    ("음식점 > 카페", "cafe"),
    ("음식점 > 간식", "cafe"),
    ("음식점", "food"),
    ("여행 > 숙박", "stay"),
    ("의료,건강 > 건강식품판매", "farm"),
    ("의료,건강", "health"),
    ("가정,생활 > 반려동물 > 동물병원", "health"),
    ("가정,생활 > 미용", "beauty"),
    ("가정,생활 > 이발소", "beauty"),
    ("가정,생활 > 편의점", "mart"),
    ("가정,생활 > 슈퍼마켓", "mart"),
    ("가정,생활 > 식품판매", "mart"),
    ("가정,생활 > 생활용품점", "mart"),
    ("교육,학문", "edu"),
    ("교통,수송", "car"),
    ("서비스,산업 > 농업", "farm"),
    ("서비스,산업 > 식품", "farm"),
    ("서비스,산업 > 축산업", "farm"),
    ("서비스,산업 > 농축산", "farm"),
    ("가정,생활 > 주말농장", "farm"),
    ("스포츠,레저", "leisure"),
    ("문화,예술", "leisure"),
    ("여행", "leisure"),
]

# Name keywords for merchants Kakao could not match to a place.
NAME_RULES = [
    ("cafe", r"카페|커피|다방|cafe|coffee|베이커리|빵|떡|꽈배기|아이스크림"),
    ("stay", r"펜션|민박|모텔|여관|호텔|캠핑|글램핑|산장|스테이|숙박|풀빌라"),
    ("health", r"약국|의원|한의원|치과|병원|의료|요양"),
    ("beauty", r"미용|헤어|네일|이용원|에스테틱|뷰티|피부"),
    ("edu", r"학원|교습소|공부방|어학"),
    ("car", r"주유소|정비|카센|타이어|모터스|오토바이|자동차|세차|중기|건기|운수|택시"),
    ("mart", r"마트|슈퍼|편의점|상회|할인|정육|축산물|청과|철물|자재|문구|서점|꽃|플라워|안경|농약|이불"),
    ("farm", r"농원|농장|영농|약초|곶감|버섯|양봉|벌꿀|꿀|건강원|농산|발효|식품|산삼|특산물|죽염|백수오|산야초|부각|양식장|조합법인|농업회사|과수원|사과|딸기|고사리|와송|인삼|농부"),
    ("food", r"식당|가든|국밥|횟집|반점|치킨|통닭|갈비|식육|짜장|분식|족발|냉면|추어|국수|백숙|밥상|한우|흑돼지|오리|짬뽕|해장국|찜|김밥|버거|피자|뷔페|구이|순두부|칼국수|아구|장어|회센|탕|국시|도시락|각$|성$"),
    ("leisure", r"래프팅|레포츠|레저|골프|당구|체육|볼링|승마|공방|갤러리|박물관|천문대|노래|PC방|수영|필라테스|요가|낚시"),
]


def load_rows():
    path = sorted(glob.glob(str(ROOT / "data/source/*.xlsx")))[-1]
    ws = openpyxl.load_workbook(path).active
    rows = []
    for no, name, zipc, addr in ws.iter_rows(min_row=4, max_col=4, values_only=True):
        if not name:
            continue
        rows.append(
            {
                "no": int(no),
                "name": str(name).strip(),
                "zip": str(zipc or "").strip(),
                "addr": re.sub(r"\s+", " ", str(addr or "").strip()),
            }
        )
    return rows


def group_of(kakao_cat, name):
    if kakao_cat:
        for prefix, g in KAKAO_RULES:
            if kakao_cat.startswith(prefix):
                return g
    for g, pattern in NAME_RULES:
        if re.search(pattern, name, re.I):
            return g
    return "etc"


def short_cat(kakao_cat):
    """'음식점 > 한식 > 국밥' -> '한식 · 국밥' (drop the top level, keep two levels)."""
    if not kakao_cat:
        return ""
    parts = [p.strip() for p in kakao_cat.split(">")]
    tail = parts[1:3] if len(parts) > 1 else parts
    return " · ".join(tail)


def write_queries():
    """Write data/source/queries.json ([no, name, address]) for scripts/geocode.mjs."""
    out = []
    for r in load_rows():
        m = re.match(r"(?:경상남도|경남)\s+산청군\s+(\S+[읍면])\s+(\S+(?:로|길))\s?(\d+(?:-\d+)?)", r["addr"])
        if m:
            q = f"경남 산청군 {m.group(1)} {m.group(2)} {m.group(3)}"
        elif re.match(r"(?:경상남도|경남)\s+산청군", r["addr"]):
            q = " ".join(r["addr"].split()[:5])
        else:
            continue
        out.append([r["no"], r["name"], q])
    path = ROOT / "data/source/queries.json"
    path.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    print("wrote", path, len(out))


def main():
    geo = json.loads((ROOT / "data/geocode.json").read_text(encoding="utf-8"))
    cats = geo["cats"]
    by_no = {r[0]: r for r in geo["rows"]}

    # Manual corrections (e.g. branches listed under the head office address).
    ov_path = ROOT / "data/overrides.json"
    overrides = json.loads(ov_path.read_text(encoding="utf-8")) if ov_path.exists() else {}

    merchants, outside = [], []
    for r in load_rows():
        m = re.match(r"(?:경상남도|경남)\s+산청군\s+(\S+[읍면])", r["addr"])
        if not m:
            outside.append({"no": r["no"], "name": r["name"], "addr": r["addr"]})
            continue
        g = by_no.get(r["no"])
        ov = overrides.get(str(r["no"]))
        if ov:
            if ov.get("name_check") and ov["name_check"] not in r["name"]:
                raise SystemExit(f"override {r['no']} expects '{ov['name_check']}' but row is '{r['name']}'")
            g = [r["no"], ov["lat"], ov["lng"], ov["pid"], g[4] if g else -1, ov["tel"], 1]
            r["addr"] = ov["addr"]
            m = re.match(r"(?:경상남도|경남)\s+산청군\s+(\S+[읍면])", r["addr"])
        kakao_cat = cats[g[4]] if g and g[4] >= 0 else ""
        merchants.append(
            {
                "no": r["no"],
                "name": r["name"],
                "addr": r["addr"],
                "emd": m.group(1),
                "lat": g[1] if g else None,
                "lng": g[2] if g else None,
                "pid": g[3] if g else "",
                "cat": short_cat(kakao_cat),
                "grp": group_of(kakao_cat, r["name"]),
                "tel": g[5] if g else "",
                "prec": g[6] if g else 3,
            }
        )

    payload = {
        "asOf": "2026-06",
        "count": len(merchants) + len(outside),
        "merchants": merchants,
        "outside": outside,
    }
    js = "window.MERCHANTS = " + json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + ";\n"
    (ROOT / "data/merchants.js").write_text(js, encoding="utf-8")

    from collections import Counter

    print("merchants", len(merchants), "outside", len(outside))
    print("no coords", sum(1 for x in merchants if x["lat"] is None))
    print("kakao place", sum(1 for x in merchants if x["pid"]))
    print(Counter(x["grp"] for x in merchants).most_common())


if __name__ == "__main__":
    import sys

    if "--queries" in sys.argv:
        write_queries()
    else:
        main()
