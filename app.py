from __future__ import annotations
import os, re, json, sqlite3, hashlib
from pathlib import Path
from datetime import datetime
import pandas as pd
import streamlit as st
import plotly.express as px
import plotly.graph_objects as go
from modules.v36_features import (migrate_schema, compliance_metrics, alarm_summary, ta_summary,
    persist_findings, save_approval, latest_approval, build_excel_report, build_pdf_report)
from ui.theme import apply_workbench_theme, render_brand_header, render_sidebar_brand
from core.settings import settings
from core.qc_engine import (infer_rat, filter_ndb, filter_ran, cell_match_key, compare_ndb_ran)

BASE = Path(__file__).resolve().parent
DB_ROOT = settings.data_root
OUT_ROOT = settings.output_root
HISTORY_DB = settings.sqlite_history_path
LOG_DIR = settings.log_dir
FOLDERS = {
    "NDB": "01_NDB",
    "RAN Report": "02_RAN_Report",
    "Dump Config": "03_Dump_Config",
    "Alarm": "04_Alarm",
    "TA": "05_TA",
}
SUPPORTED_XLS = {".xlsx", ".xlsm", ".xls"}
TA_PREFIX = "L.RA.TA.UE.Index"

st.set_page_config(page_title="RAN Configuration Workbench", page_icon="📡", layout="wide", initial_sidebar_state="expanded")
apply_workbench_theme()

# ---------------------------- common utilities ----------------------------
def init_history():
    HISTORY_DB.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(HISTORY_DB) as con:
        con.execute("""CREATE TABLE IF NOT EXISTS audit_runs(
            run_id TEXT PRIMARY KEY, scanned_at TEXT, site_name TEXT, enodeb_name TEXT,
            alarm_source TEXT, ndb_status TEXT, ran_status TEXT, ndb_cells INTEGER,
            ran_cells INTEGER, matched_cells INTEGER, mismatch_cells INTEGER,
            alarm_rows INTEGER, uncleared_alarms INTEGER, ta_rows INTEGER, source_manifest TEXT)""")

def log(message):
    LOG_DIR.mkdir(exist_ok=True)
    with (LOG_DIR / "audit.log").open("a", encoding="utf-8") as f:
        f.write(f"[{datetime.now().isoformat(timespec='seconds')}] {message}\n")

def files_in(category):
    folder = DB_ROOT / FOLDERS[category]
    if not folder.exists(): return []
    return [p for p in folder.rglob("*") if p.is_file() and p.suffix.lower() in SUPPORTED_XLS.union({".csv"})]

def file_signature(category):
    """Stable cache key: path + nanosecond mtime + size for source files."""
    items=[]
    for p in files_in(category):
        try:
            stt=p.stat()
            items.append((str(p), stt.st_mtime_ns, stt.st_size))
        except OSError:
            continue
    return tuple(sorted(items))

def date_key(path):
    m = re.search(r"(20\d{6})", path.name)
    if m:
        try: return datetime.strptime(m.group(1), "%Y%m%d")
        except ValueError: pass
    m = re.search(r"(20\d{4})", path.name)
    if m:
        try: return datetime.strptime(m.group(1), "%Y%m")
        except ValueError: pass
    return datetime.fromtimestamp(path.stat().st_mtime)

def area_for_ndb_file(path):
    base = DB_ROOT / FOLDERS["NDB"]
    try:
        rel = path.relative_to(base)
        return rel.parts[0] if len(rel.parts) > 1 else "Default / Root"
    except Exception:
        return "Default / Root"

def ndb_area_options():
    vals = sorted({area_for_ndb_file(p) for p in files_in("NDB")})
    return vals or ["Default / Root"]

def latest_file(category, area=None):
    candidates = files_in(category)
    if category == "NDB" and area:
        candidates = [p for p in candidates if area_for_ndb_file(p) == area]
    if not candidates: return None
    return sorted(candidates, key=lambda p: (date_key(p), p.stat().st_mtime, p.name))[-1]

def norm(value):
    if pd.isna(value): return ""
    return re.sub(r"\s+", " ", str(value).strip()).upper()

def site_base(value):
    s = norm(value)
    s = re.sub(r"_(2G|3G|4G|5G)$", "", s)
    return s

def is_blank(value):
    return pd.isna(value) or str(value).strip() in {"", "-", "NULL", "nan", "None"}

def same_value(a, b):
    if is_blank(a) and is_blank(b): return True
    if is_blank(a) != is_blank(b): return False
    try:
        fa, fb = float(str(a).replace(",", "")), float(str(b).replace(",", ""))
        return abs(fa-fb) < 1e-8
    except Exception:
        return norm(a) == norm(b)

def unique_options(values):
    vals = sorted({str(v).strip() for v in values if not is_blank(v)})
    return vals

def newest_manifest(area=None):
    """Manifest all independent NDB and RAN databases without merging source workbooks."""
    out = {}
    for cat in FOLDERS:
        fs = files_in(cat)
        if cat == "NDB":
            out[cat] = [p.name for p in ndb_files_for_area(area)]
        elif cat == "RAN Report":
            out[cat] = [p.name for p in sorted(fs, key=lambda x: (date_key(x), x.stat().st_mtime, x.name))]
        elif cat in {"Alarm", "TA", "Dump Config"}:
            out[cat] = [p.name for p in fs]
        else:
            out[cat] = []
    return out

# ---------------------------- data readers ----------------------------
@st.cache_data(show_spinner=False)
def load_ndb_cached(path_text, mtime):
    return pd.read_excel(path_text, sheet_name=0, engine="openpyxl")

def load_ndb(area=None):
    """Backward-compatible latest NDB loader; multi-database audit uses detect_ndb_source."""
    p = latest_file("NDB", area)
    if p is None: return pd.DataFrame(), None
    return load_ndb_cached(str(p), p.stat().st_mtime), p

@st.cache_data(show_spinner=False)
def load_ndb_file_cached(path_text, mtime_ns, size):
    return pd.read_excel(path_text, sheet_name=0, engine="openpyxl")

def ndb_files_for_area(area=None):
    candidates = files_in("NDB")
    if area:
        candidates = [p for p in candidates if area_for_ndb_file(p) == area]
    return sorted(candidates, key=lambda x: (date_key(x), x.stat().st_mtime, x.name), reverse=True)

def load_ndb_candidates(area=None):
    """Load NDB workbooks independently; do not concatenate or modify source files."""
    loaded=[]
    for path in ndb_files_for_area(area):
        try:
            stat=path.stat()
            frame=load_ndb_file_cached(str(path), stat.st_mtime_ns, stat.st_size)
            if not frame.empty and "SITE_NAME" in frame.columns:
                loaded.append((path, frame))
        except Exception as exc:
            log(f"NDB auto-detect skipped | {path.name} | {type(exc).__name__}: {exc}")
    return loaded

def ndb_site_options(candidates):
    values=[]
    for _path, frame in candidates:
        if "SITE_NAME" in frame.columns:
            values.extend(frame["SITE_NAME"].tolist())
    return unique_options(values)

def ndb_rows_for_site_selection(candidates, site):
    """Selection helper only: collect NE choices without combining source workbooks."""
    rows=[]
    for _path, frame in candidates:
        if "SITE_NAME" not in frame.columns: continue
        part=frame[frame["SITE_NAME"].astype(str).map(norm)==norm(site)]
        if not part.empty: rows.append(part)
    return rows

def detect_ndb_source(site, enodeb, area=None):
    """Search all NDB workbooks independently and select the strongest matching source."""
    matches=[]
    for path, frame in load_ndb_candidates(area):
        rows=filter_ndb(frame, site, enodeb)
        if not rows.empty:
            matches.append({"path":path, "rows":rows, "row_count":len(rows)})
    if not matches:
        return None, pd.DataFrame(), []
    selected=max(matches, key=lambda x: x["row_count"])
    return selected["path"], selected["rows"], [
        {"file":m["path"].name, "matching_rows":m["row_count"]} for m in matches
    ]

@st.cache_data(show_spinner=False)
def load_alarm_file_cached(path_text, mtime_ns, size):
    p = Path(path_text)
    result = []
    try:
        xls = pd.ExcelFile(p)
        for sheet in xls.sheet_names:
            raw = pd.read_excel(p, sheet_name=sheet, header=None, nrows=20)
            header_row = None
            for i, row in raw.iterrows():
                vals = {norm(x) for x in row.tolist() if not is_blank(x)}
                if {"ALARM ID", "NAME", "ALARM SOURCE"}.issubset(vals):
                    header_row = i
                    break
            if header_row is None: continue
            df = pd.read_excel(p, sheet_name=sheet, header=header_row)
            df = df.dropna(how="all")
            # Keep actual source column names; remove only completely empty unnamed columns.
            df = df.loc[:, [not str(c).lower().startswith("unnamed") for c in df.columns]]
            if "Alarm ID" in df.columns and "Alarm Source" in df.columns:
                df["_Source File"] = p.name
                df["_Source Sheet"] = sheet
                result.append(df)
    except Exception:
        return []
    return result

@st.cache_data(show_spinner=False, max_entries=8)
def load_alarms_cached(signature):
    frames=[]
    for path_text, mtime_ns, size in signature:
        p=Path(path_text)
        # The per-file loader is also cached; the signature ensures changed files invalidate this aggregate.
        frames.extend(load_alarm_file_cached(str(p), mtime_ns, size))
    if not frames: return pd.DataFrame()
    df=pd.concat(frames,ignore_index=True,sort=False)
    raw_cols=[c for c in df.columns if not str(c).startswith("_Source ")]
    key=df[raw_cols].fillna("").astype(str).apply(lambda r:"\x1f".join(r.values),axis=1)
    return df.loc[~key.duplicated()].copy()

def load_alarms():
    return load_alarms_cached(file_signature("Alarm"))

@st.cache_data(show_spinner=False)
def load_ran_sheet_cached(path_text, mtime, sheet):
    return pd.read_excel(path_text, sheet_name=sheet, engine="openpyxl")

def get_ran_sheet(ran_path, rat):
    if ran_path is None: return pd.DataFrame(), None
    try:
        xls=pd.ExcelFile(ran_path)
        names=xls.sheet_names
        if rat=="4G": target=next((s for s in names if "4G" in s.upper()),None)
        elif rat=="5G": target=next((s for s in names if "5G" in s.upper()),None)
        else: target=next((s for s in names if "2G" in s.upper()),None)
        if target is None: return pd.DataFrame(),None
        return load_ran_sheet_cached(str(ran_path),ran_path.stat().st_mtime,target),target
    except Exception:
        return pd.DataFrame(),None


def detect_ran_source(site, enodeb, rat):
    """Search every RAN workbook independently. Never concatenate source databases.

    If more than one workbook contains the requested target, select the workbook
    with the largest matching cell set; break ties by newest snapshot ordering.
    Return all matches for transparent source reporting.
    """
    matches=[]
    candidates=sorted(files_in("RAN Report"), key=lambda x: (date_key(x), x.stat().st_mtime, x.name), reverse=True)
    for path in candidates:
        try:
            sheet_df, sheet_name=get_ran_sheet(path, rat)
            if sheet_name is None or sheet_df.empty:
                continue
            rows=filter_ran(sheet_df, rat, site, enodeb)
            if not rows.empty:
                matches.append({"path":path, "sheet":sheet_name, "rows":rows, "row_count":len(rows)})
        except Exception as exc:
            log(f"RAN auto-detect skipped | {path.name} | {type(exc).__name__}: {exc}")
    if not matches:
        return None, None, pd.DataFrame(), []
    # candidates are already newest-first; stable max keeps newest on row-count ties.
    selected=max(matches, key=lambda x: x["row_count"])
    return selected["path"], selected["sheet"], selected["rows"], [
        {"file":m["path"].name, "sheet":m["sheet"], "matching_rows":m["row_count"]} for m in matches
    ]

def _xlsx_sheet_targets(path):
    """Read only workbook.xml metadata; avoids loading workbook shared data/worksheets."""
    import zipfile, xml.etree.ElementTree as ET, posixpath
    ns={"m":"http://schemas.openxmlformats.org/spreadsheetml/2006/main",
        "r":"http://schemas.openxmlformats.org/officeDocument/2006/relationships",
        "rel":"http://schemas.openxmlformats.org/package/2006/relationships"}
    with zipfile.ZipFile(path,"r") as z:
        wb=ET.fromstring(z.read("xl/workbook.xml"))
        rel_root=ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
        rels={r.attrib.get("Id"):r.attrib.get("Target") for r in rel_root.findall("rel:Relationship",ns)}
        out=[]
        for sh in wb.findall("m:sheets/m:sheet",ns):
            rid=sh.attrib.get("{"+ns["r"]+"}id")
            target=rels.get(rid,"")
            if target.startswith("/"):
                target=target.lstrip("/")
            else:
                target=posixpath.normpath(posixpath.join("xl",target))
            out.append((sh.attrib.get("name",target),target))
        return out

def _excel_col_index(cell_ref):
    letters=re.match(r"([A-Z]+)",cell_ref or "")
    if not letters: return 0
    value=0
    for ch in letters.group(1): value=value*26+ord(ch)-64
    return value-1

def _xlsx_shared_strings(z):
    import xml.etree.ElementTree as ET
    if "xl/sharedStrings.xml" not in z.namelist(): return []
    ns="{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
    values=[]
    with z.open("xl/sharedStrings.xml") as f:
        for _,elem in ET.iterparse(f,events=("end",)):
            if elem.tag==ns+"si":
                values.append("".join(t.text or "" for t in elem.iter(ns+"t")))
                elem.clear()
    return values

def _xlsx_cell_value(cell, shared):
    import xml.etree.ElementTree as ET
    ns="{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
    typ=cell.attrib.get("t")
    if typ=="inlineStr":
        return "".join(t.text or "" for t in cell.iter(ns+"t"))
    v=cell.find(ns+"v")
    if v is None or v.text is None: return None
    value=v.text
    if typ=="s":
        try: return shared[int(value)]
        except Exception: return value
    if typ=="b": return value=="1"
    if typ in {"str","e"}: return value
    try:
        number=float(value)
        return int(number) if number.is_integer() else number
    except Exception:
        return value

@st.cache_data(show_spinner=False, max_entries=4)
def dump_command_catalog_cached(signature):
    """Read workbook sheet metadata only; no command worksheet rows are parsed."""
    catalog=[]
    for path_text, mtime_ns, size in signature:
        p=Path(path_text)
        try:
            if p.suffix.lower() in {".xlsx", ".xlsm"}:
                for sheet,target in _xlsx_sheet_targets(p):
                    catalog.append({"path":str(p),"file":p.name,"sheet":sheet,"sheet_xml":target,"command":sheet})
            elif p.suffix.lower()==".xls":
                with pd.ExcelFile(p) as xls:
                    for sheet in xls.sheet_names:
                        catalog.append({"path":str(p),"file":p.name,"sheet":sheet,"sheet_xml":None,"command":sheet})
            elif p.suffix.lower()==".csv":
                catalog.append({"path":str(p),"file":p.name,"sheet":"CSV","sheet_xml":None,"command":p.stem})
        except Exception as exc:
            log(f"Dump catalog skipped | {p.name} | {type(exc).__name__}: {exc}")
    return catalog

def search_dump_commands(catalog, query):
    """Search command names only; does not read worksheet rows."""
    q=norm(query)
    if not q: return []
    exact=[x for x in catalog if q == norm(x["command"]) or q == norm(x["sheet"])]
    if exact: return exact
    return [x for x in catalog if q in norm(x["command"]) or q in norm(x["sheet"]) or q in norm(x["file"])]

@st.cache_data(show_spinner=False, max_entries=24)
def load_one_dump_command_cached(path_text, mtime_ns, size, sheet, sheet_xml, site, enodeb):
    """Parse only the selected XLSX worksheet XML and retain rows for the selected site."""
    import zipfile, xml.etree.ElementTree as ET
    p=Path(path_text)
    aliases={site_base(site),site_base(enodeb)}
    aliases={a for a in aliases if a}
    try:
        if p.suffix.lower() in {".xlsx", ".xlsm"} and sheet_xml:
            ns="{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
            exact_rows=[]; prefix_rows=[]; headers=None; ne_idx=None
            with zipfile.ZipFile(p,"r") as z:
                shared=_xlsx_shared_strings(z)
                with z.open(sheet_xml) as xml_file:
                    for _,elem in ET.iterparse(xml_file,events=("end",)):
                        if elem.tag!=ns+"row": continue
                        cells=[]
                        for cell in elem.findall(ns+"c"):
                            idx=_excel_col_index(cell.attrib.get("r",""))
                            while len(cells)<=idx: cells.append(None)
                            cells[idx]=_xlsx_cell_value(cell,shared)
                        elem.clear()
                        if headers is None:
                            headers=[str(v).strip() if v is not None else f"Unnamed: {i}" for i,v in enumerate(cells)]
                            ne_idx=next((i for i,h in enumerate(headers) if norm(h)=="NENAME"),None)
                            if ne_idx is None: break
                            continue
                        if ne_idx>=len(cells): continue
                        ne=site_base(cells[ne_idx])
                        if not ne: continue
                        values=tuple(cells[:len(headers)])+(None,)*max(0,len(headers)-len(cells))
                        if ne in aliases: exact_rows.append(values)
                        elif any(ne.startswith(a) or a.startswith(ne) for a in aliases): prefix_rows.append(values)
            rows=exact_rows if exact_rows else prefix_rows
            df=pd.DataFrame(rows,columns=headers) if headers else pd.DataFrame()
        elif p.suffix.lower()==".xls":
            df=pd.read_excel(p,sheet_name=sheet)
            if "NEName" not in df.columns: return pd.DataFrame()
            ne=df["NEName"].astype(str).map(site_base); exact=ne.isin(aliases)
            df=df[exact] if exact.any() else df[ne.map(lambda x:any(x and (x.startswith(a) or a.startswith(x)) for a in aliases))]
        elif p.suffix.lower()==".csv":
            chunks=[]
            for chunk in pd.read_csv(p,chunksize=50000,low_memory=False):
                if "NEName" not in chunk.columns: continue
                ne=chunk["NEName"].astype(str).map(site_base); exact=ne.isin(aliases)
                keep=exact if exact.any() else ne.map(lambda x:any(x and (x.startswith(a) or a.startswith(x)) for a in aliases))
                if keep.any(): chunks.append(chunk[keep])
            df=pd.concat(chunks,ignore_index=True) if chunks else pd.DataFrame()
        else:
            return pd.DataFrame()
        if df.empty: return df
        df=df.dropna(how="all").copy()
        df["_Dump File"]=p.name; df["_Dump Sheet"]=sheet
        return df
    except Exception as exc:
        log(f"Dump command read failed | {p.name} | {sheet} | {type(exc).__name__}: {exc}")
        return pd.DataFrame()

def load_one_dump_command(item, site, enodeb):
    p=Path(item["path"]); stt=p.stat()
    return load_one_dump_command_cached(str(p),stt.st_mtime_ns,stt.st_size,item["sheet"],item.get("sheet_xml"),site,enodeb)

@st.cache_data(show_spinner=False)
def load_ta_file_cached(path_text,mtime_ns,size):
    p=Path(path_text)
    try:
        return pd.read_csv(p,low_memory=False)
    except UnicodeDecodeError:
        return pd.read_csv(p,encoding="cp1252",low_memory=False)

@st.cache_data(show_spinner=False, max_entries=3)
def load_ta_cached(signature):
    frames=[]
    for path_text, mtime_ns, size in signature:
        p=Path(path_text)
        try:
            df=load_ta_file_cached(str(p),mtime_ns,size)
            df["_TA File"]=p.name
            frames.append(df)
        except Exception as exc:
            log(f"TA read skipped | {p.name} | {type(exc).__name__}: {exc}")
            continue
    if not frames: return pd.DataFrame()
    df=pd.concat(frames,ignore_index=True,sort=False)
    cols=[c for c in df.columns if c!="_TA File"]
    fp=pd.util.hash_pandas_object(df[cols].fillna("").astype(str),index=False)
    return df.loc[~fp.duplicated()].copy()

def load_ta():
    return load_ta_cached(file_signature("TA"))

# ---------------------------- NDB / RAN audit ----------------------------
# QC comparison primitives are shared with core.qc_engine for cross-client parity.

def render_dump_explorer(site, enodeb, run_id):
    """Search-first, read-only telecom configuration workbench viewer."""
    import html

    st.markdown("""
    <style>
      .dx-shell{background:linear-gradient(120deg,#0c1b2b 0%,#102b43 58%,#073d50 100%);border:1px solid #28536b;border-radius:18px;padding:22px 24px;margin:2px 0 16px;box-shadow:0 12px 32px rgba(0,0,0,.20)}
      .dx-top{display:flex;align-items:center;gap:13px}.dx-logo{width:48px;height:48px;border-radius:14px;display:flex;align-items:center;justify-content:center;background:linear-gradient(145deg,#0b91b5,#1460a1);box-shadow:0 5px 18px #0005}
      .dx-logo svg{width:29px;height:29px}.dx-brand{font-size:10px;letter-spacing:2px;font-weight:800;color:#70dff4}.dx-title{font-size:25px;font-weight:850;letter-spacing:-.6px;color:#f4f9ff;margin-top:2px}.dx-sub{font-size:12px;color:#b4cbdc;margin-top:3px}
      .dx-pill{display:inline-flex;align-items:center;gap:6px;border:1px solid #477087;background:#17364c;color:#d7f4fb;border-radius:30px;padding:5px 10px;font-size:10px;font-weight:750;margin:13px 6px 0 0}.dx-pill.green{border-color:#267e67;background:#103e38;color:#8cf0c8}
      .dx-section{font-size:11px;letter-spacing:1.5px;font-weight:850;color:#45cce9;text-transform:uppercase;margin:13px 0 8px}
      .dx-card{background:linear-gradient(145deg,#13283d,#101f31);border:1px solid #29445c;border-radius:13px;padding:13px 15px;min-height:82px}
      .dx-label{font-size:10px;letter-spacing:1px;text-transform:uppercase;color:#91aec4;font-weight:800}.dx-value{font-size:22px;line-height:1.2;color:#f4f8fc;font-weight:800;margin-top:8px;overflow-wrap:anywhere}.dx-hint{font-size:11px;color:#91a9bd;margin-top:5px}
      .dx-param{background:#12253a;border:1px solid #29445c;border-radius:11px;padding:11px 13px;min-height:76px;margin-bottom:8px}.dx-param-name{font-size:10px;color:#8eabc1;font-weight:800;letter-spacing:.7px;text-transform:uppercase}.dx-param-value{font-size:14px;color:#edf6fc;font-weight:650;margin-top:7px;overflow-wrap:anywhere}.dx-param-value.null{color:#71879a;font-weight:500;font-style:italic}
      .dx-group{font-size:11px;color:#63d7ee;font-weight:850;letter-spacing:1.2px;text-transform:uppercase;margin:15px 0 8px;padding-bottom:6px;border-bottom:1px solid #28465c}
      .dx-empty{border:1px dashed #36536a;border-radius:13px;padding:22px;text-align:center;color:#a8bfd0;background:#102033}
      div[data-testid="stDataFrame"]{border:1px solid #29445c;border-radius:12px;overflow:hidden}
      div[data-testid="stTabs"] button{font-size:12px;font-weight:750}
    </style>
    <div class="dx-shell">
      <div class="dx-top">
        <div class="dx-logo"><svg viewBox="0 0 32 32" fill="none" stroke="#fff" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M16 5v22M9 27h14M11 27l5-22 5 22M12 17h8M10 12h12"/><path d="M5 9a15 15 0 0 1 0 14M27 9a15 15 0 0 0 0 14M2 5a20 20 0 0 1 0 22M30 5a20 20 0 0 0 0 22"/></svg></div>
        <div><div class="dx-brand">RAN CONFIGURATION MANAGEMENT</div><div class="dx-title">Dump Config Explorer</div><div class="dx-sub">Huawei LTE & NR command viewer · Search, inspect and export configuration records</div></div>
      </div>
      <span class="dx-pill">◉ 4G LTE</span><span class="dx-pill">◉ 5G NR</span><span class="dx-pill">⌁ RF CONFIGURATION</span><span class="dx-pill green">● READ ONLY</span>
    </div>
    """, unsafe_allow_html=True)

    signature=file_signature("Dump Config")
    if not signature:
        st.markdown('<div class="dx-empty">📂 <b>No Dump Config source found</b><br>Tambahkan file ke folder 03_Dump_Config untuk mulai mencari command.</div>',unsafe_allow_html=True)
        return
    catalog=dump_command_catalog_cached(signature)
    if not catalog:
        st.warning("Tidak ditemukan sheet/command pada file Dump Config.")
        return

    st.markdown('<div class="dx-section">⌕ COMMAND SEARCH</div>',unsafe_allow_html=True)
    search_key=f"dump_command_query_{run_id}"
    results_key=f"dump_command_results_{run_id}"
    with st.form(key=f"dump_search_form_{run_id}"):
        c1,c2=st.columns([5,1])
        with c1:
            q=st.text_input("Huawei command",placeholder="Search command, e.g. DSP RETSUBUNIT or LST PDSCHCFG",key=search_key,label_visibility="collapsed")
        with c2:
            submitted=st.form_submit_button("SEARCH COMMAND  ↵",type="primary",use_container_width=True)
    if submitted:
        matches=search_dump_commands(catalog,q)
        st.session_state[results_key]=matches
        st.session_state.pop(f"dump_selected_{run_id}",None)
    matches=st.session_state.get(results_key,[])
    if not matches:
        st.markdown(f'<div class="dx-empty"><div style="font-size:28px">⌕</div><b>Search a Huawei command to inspect its configuration</b><br><span style="font-size:12px">{len(catalog):,} command sheets indexed across {len(signature):,} source files. No command data is loaded until you search.</span></div>',unsafe_allow_html=True)
        return

    labels=[f"{x['command']}  ·  {x['file']}" for x in matches]
    selected_label=st.selectbox("Matching commands",labels,key=f"dump_selected_{run_id}",label_visibility="collapsed")
    selected=matches[labels.index(selected_label)]
    with st.spinner(f"Loading {selected['command']} for {site}..."):
        df=load_one_dump_command(selected,site,enodeb)
    if df.empty:
        st.warning("Command ditemukan, tetapi tidak ada record dengan NEName yang cocok untuk site/eNodeB ini. Periksa nama NE pada file dump.")
        return

    visible=[c for c in df.columns if not str(c).startswith("_Dump ")]
    ne_count=df["NEName"].nunique() if "NEName" in df.columns else 0
    command=selected["command"]
    command_type="5G NR" if any(x in command.upper() for x in ["NR", "GNB", "NRCELL", "NRDU"]) else "4G LTE"
    st.caption(f"SITE  /  {site}     ·     COMMAND  /  {command}     ·     SHEET  /  {selected['sheet']}     ·     SOURCE  /  {selected['file']}")
    m1,m2,m3,m4=st.columns(4)
    for col,label,value,hint in [
        (m1,"SELECTED COMMAND",command,command_type),
        (m2,"SITE RECORDS",f"{len(df):,}","Records matching selected site"),
        (m3,"NETWORK ELEMENTS",f"{ne_count:,}","Unique NEName values"),
        (m4,"AVAILABLE PARAMETERS",f"{len(visible):,}","Columns in selected command")]:
        with col:
            st.markdown(f'<div class="dx-card"><div class="dx-label">{html.escape(label)}</div><div class="dx-value">{html.escape(str(value))}</div><div class="dx-hint">{html.escape(hint)}</div></div>',unsafe_allow_html=True)

    st.markdown('<div class="dx-section">⌕ FILTER COMMAND RECORDS</div>',unsafe_allow_html=True)
    f1,f2=st.columns([4,1])
    with f1:
        value_search=st.text_input("Search parameter values",placeholder="Search device name, sector, tilt, band, status...",key=f"dump_value_{run_id}_{selected['sheet']}",label_visibility="collapsed")
    with f2:
        page_size=st.selectbox("Rows per page",[25,50,100],index=1,key=f"dump_pagesize_{run_id}_{selected['sheet']}",label_visibility="collapsed")
    view=df
    if value_search.strip():
        term=value_search.strip()
        mask=df[visible].astype(str).apply(lambda col: col.str.contains(re.escape(term),case=False,na=False)).any(axis=1)
        view=df[mask]
    if view.empty:
        st.info("Tidak ada record yang cocok dengan pencarian nilai.")
        return
    total_pages=max(1,(len(view)+page_size-1)//page_size)
    p1,p2=st.columns([1,5])
    with p1:
        page=st.number_input("Page",min_value=1,max_value=total_pages,value=1,step=1,key=f"dump_page_{run_id}_{selected['sheet']}")
    start=(int(page)-1)*page_size
    page_df=view.iloc[start:start+page_size]
    with p2:
        st.markdown(f'<div style="padding:29px 0 0;color:#91a9bd;font-size:12px">Showing <b style="color:#e6f4fc">{start+1:,}–{start+len(page_df):,}</b> of <b style="color:#e6f4fc">{len(view):,}</b> matching records</div>',unsafe_allow_html=True)

    # Keep the default grid focused; the full schema remains available in the Raw Data tab.
    preferred=["NEName","Device Name","Device No.","Subunit Name","Subunit No.","Local cell ID","NR DU Cell TRP ID","Online Status","Actual Tilt(0.1degree)","Actual Sector ID","Azimuth(degree)","Tilt(degree)"]
    key_cols=[c for c in preferred if c in visible]
    if not key_cols: key_cols=visible[:8]
    show_all=st.checkbox("Show all command columns",value=False,key=f"dump_allcols_{run_id}_{selected['sheet']}")
    grid_cols=visible if show_all else key_cols
    st.dataframe(page_df[grid_cols],use_container_width=True,hide_index=True,height=min(470, max(220, 42+len(page_df)*35)))

    row_labels=[]
    for rid,row in page_df.iterrows():
        parts=[]
        for key in ["Device Name","Device No.","Subunit Name","Local cell ID","NR DU Cell TRP ID"]:
            if key in page_df.columns and pd.notna(row.get(key)) and str(row.get(key)).strip().upper()!="NULL":
                parts.append(f"{key}: {row.get(key)}")
        row_labels.append(f"Record {start+len(row_labels)+1}  |  " + ("  ·  ".join(parts[:3]) if parts else f"Row {rid+1}"))
    st.markdown('<div class="dx-section">▣ CONFIGURATION RECORD DETAIL</div>',unsafe_allow_html=True)
    chosen_label=st.selectbox("Select a record to inspect its parameters",row_labels,key=f"dump_record_{run_id}_{selected['sheet']}")
    record=page_df.iloc[row_labels.index(chosen_label)]

    def classify_parameter(name):
        n=str(name).lower()
        if any(k in n for k in ["nename","neinfo","device","subunit","cell id","cell name","trp id","sector id"]): return "IDENTITY & NETWORK ELEMENT"
        if any(k in n for k in ["tilt","azimuth","antenna","beamwidth","gain","bearing","ret","band","power","epre","rs"]): return "RF & ANTENNA PARAMETERS"
        if any(k in n for k in ["status","switch","enable","state","mode","alarm","online"]): return "OPERATIONAL STATUS"
        return "OTHER PARAMETERS"

    groups={"IDENTITY & NETWORK ELEMENT":[],"RF & ANTENNA PARAMETERS":[],"OPERATIONAL STATUS":[],"OTHER PARAMETERS":[]}
    for c in visible:
        if pd.isna(record.get(c)): continue
        groups[classify_parameter(c)].append((str(c),str(record.get(c))))
    left,right=st.columns([1.65,1])
    with left:
        for group_name,items in groups.items():
            if not items: continue
            st.markdown(f'<div class="dx-group">{html.escape(group_name)} · {len(items)} PARAMETERS</div>',unsafe_allow_html=True)
            for offset in range(0,len(items),2):
                pair=items[offset:offset+2]
                cols=st.columns(2)
                for col,(name,value) in zip(cols,pair):
                    with col:
                        val_cls="null" if value.strip().upper() in {"NULL","NAN","NONE"} else ""
                        st.markdown(f'<div class="dx-param"><div class="dx-param-name">{html.escape(name)}</div><div class="dx-param-value {val_cls}">{html.escape(value)}</div></div>',unsafe_allow_html=True)
    with right:
        st.markdown('<div class="dx-section">▣ RECORD IDENTITY</div>',unsafe_allow_html=True)
        identity_keys=["NEName","Device Name","Device No.","Subunit Name","Subunit No.","Local cell ID","NR DU Cell TRP ID","Online Status"]
        shown=0
        for key in identity_keys:
            if key in record.index and pd.notna(record[key]):
                shown+=1
                val=html.escape(str(record[key]))
                st.markdown(f'<div class="dx-card" style="min-height:0;margin-bottom:8px"><div class="dx-label">{html.escape(key)}</div><div style="font-size:14px;color:#eff7fc;font-weight:700;margin-top:6px">{val}</div></div>',unsafe_allow_html=True)
        if not shown: st.caption("No standard identity fields available for this command.")
        st.markdown('<div class="dx-section">▤ SOURCE INFORMATION</div>',unsafe_allow_html=True)
        st.markdown(f'<div class="dx-card" style="min-height:0"><div class="dx-label">SOURCE FILE</div><div style="font-size:12px;color:#eff7fc;margin-top:6px;overflow-wrap:anywhere">{html.escape(selected["file"])}</div><div class="dx-label" style="margin-top:13px">WORKSHEET</div><div style="font-size:12px;color:#eff7fc;margin-top:6px">{html.escape(selected["sheet"])}</div><div class="dx-label" style="margin-top:13px">ACCESS MODE</div><div style="font-size:12px;color:#8cf0c8;font-weight:800;margin-top:6px">READ ONLY · ORIGINAL FILE UNCHANGED</div></div>',unsafe_allow_html=True)
        st.download_button("⬇  EXPORT SELECTED RECORD",pd.DataFrame([record[visible]]).to_csv(index=False).encode("utf-8-sig"),file_name=f"{site}_{selected['sheet']}_Record.csv",mime="text/csv",key=f"dump_record_dl_{run_id}_{selected['sheet']}",use_container_width=True)

    with st.expander("▤ RAW DATA · Full selected command records",expanded=False):
        st.caption("Raw source columns are preserved. Preview is capped at 1,000 rows; export includes all matching records.")
        st.dataframe(view[visible].head(1000),use_container_width=True,hide_index=True)
        st.download_button("⬇  EXPORT FULL COMMAND CSV",view[visible].to_csv(index=False).encode("utf-8-sig"),file_name=f"{site}_{selected['sheet']}.csv",mime="text/csv",key=f"dump_raw_dl_{run_id}_{selected['sheet']}")


# ---------------------------- module filters ----------------------------
def filter_alarm(alarms, alarm_source):
    if alarms.empty or not alarm_source or "Alarm Source" not in alarms.columns:
        return pd.DataFrame()
    return alarms[alarms["Alarm Source"].astype(str).map(norm)==norm(alarm_source)].copy()

def filter_dump(frames, site, enodeb):
    out=[]
    aliases={site_base(site),site_base(enodeb)}
    for df in frames:
        if "NEName" in df.columns:
            mask=df["NEName"].astype(str).map(site_base).isin(aliases)
            # If NEName is not an exact base, allow prefix match but avoid empty match.
            if not mask.any():
                mask=df["NEName"].astype(str).map(norm).apply(lambda x:any(a and (x.startswith(a) or a.startswith(x)) for a in aliases))
            f=df[mask].copy()
            if not f.empty: out.append(f)
    return out

def filter_ta(ta, site, enodeb):
    if ta.empty: return ta.copy()
    target={site_base(site),site_base(enodeb)}
    mask=pd.Series(False,index=ta.index)
    for col in ["eNodeB Name","eNodeB Function Name"]:
        if col in ta.columns:
            mask |= ta[col].astype(str).map(site_base).isin(target)
    if "Cell Name" in ta.columns:
        cell=ta["Cell Name"].astype(str).map(norm)
        # Use the full selected site token; avoid broad partial-name matches.
        site_token=norm(site)
        if site_token:
            mask |= cell.str.contains(re.escape(site_token),na=False)
    return ta[mask].copy()

def get_site_coordinates(ndb_rows):
    if ndb_rows.empty: return None
    for _,r in ndb_rows.iterrows():
        try:
            lon=float(r["X_LONGITUDE"]); lat=float(r["Y_LATITUDE"])
            if -180<=lon<=180 and -90<=lat<=90:
                return lat,lon
        except Exception: pass
    return None

def make_ta_map(lat,lon,counts,step_m):
    import folium
    m=folium.Map(location=[lat,lon],zoom_start=16,control_scale=True,tiles="OpenStreetMap")
    folium.Marker([lat,lon],tooltip="Site location from NDB",
                  popup=f"Site coordinate: {lat:.6f}, {lon:.6f}",
                  icon=folium.Icon(color="red",icon="tower-cell",prefix="fa")).add_to(m)
    colors=["#2563eb","#0d9488","#16a34a","#65a30d","#ca8a04","#ea580c",
            "#dc2626","#c026d3","#7c3aed","#4f46e5","#0891b2","#475569"]
    for i in range(12):
        radius=(i+1)*step_m
        count=int(counts.get(f"{TA_PREFIX}{i}",0))
        folium.Circle([lat,lon],radius=radius,color=colors[i],weight=2,fill=False,
            tooltip=f"Index {i} · {radius:.1f} m · {count:,} records",
            popup=f"TA Index {i}<br>Outer range boundary: {radius:.1f} m<br>Records: {count:,}").add_to(m)
    folium.CircleMarker([lat,lon],radius=5,color="#111827",fill=True,fill_opacity=1).add_to(m)
    return m

# ---------------------------- UI ----------------------------
init_history()
render_brand_header("V3.7.4 NDB + RAN MULTI-DATABASE AUTO DETECTION")
st.markdown("<div class='ran-section-label'>WORKSPACE · SITE AUDIT</div>", unsafe_allow_html=True)
st.caption("Automated RAN QC · Search-Only Dump Explorer · Compliance · Alarm & TA Intelligence · Site Map · Historical Audit · Excel/PDF Reporting")

# Area-aware NDB selection supports one NDB snapshot per Area subfolder.
def reset_area_dependent_state():
    for key in ["site_select", "enodeb_select", "audit_result", "v36_batch_result"]:
        st.session_state.pop(key, None)

with st.sidebar:
    render_sidebar_brand()
    st.caption("LOCAL ENGINEERING ENVIRONMENT · READ ONLY")
    st.divider()
    st.subheader("Data Workspace")
    st.subheader("Area Selection")
    selected_area = st.selectbox("NDB Area", ndb_area_options(), key="ndb_area_select",
                                 on_change=reset_area_dependent_state)

ndb_candidates=load_ndb_candidates(selected_area)
if not ndb_candidates:
    st.error("NDB tidak ditemukan atau tidak memiliki kolom SITE_NAME. Masukkan file NDB ke database_Concheck/01_NDB.")
    st.stop()

alarms=load_alarms()
site_options=ndb_site_options(ndb_candidates)
if not site_options:
    st.error("Kolom SITE_NAME tidak ditemukan pada seluruh database NDB.")
    st.stop()

with st.sidebar:
    st.subheader("Database Status")
    st.write(f"**Selected Area:** {selected_area}")
    for cat in FOLDERS:
        fs=files_in(cat)
        if cat == "NDB":
            ndb_files=ndb_files_for_area(selected_area)
            st.write(f"**NDB:** {len(ndb_files)} database file(s) · Auto Detection")
            for ndb_file in ndb_files:
                st.caption(f"• {ndb_file.name}")
        elif cat == "RAN Report":
            st.write(f"**RAN Report:** {len(fs)} database file(s)")
            for ran_file in sorted(fs, key=lambda x: x.name):
                st.caption(f"• {ran_file.name}")
        else:
            st.write(f"**{cat}:** {len(fs)} file(s)")
    st.divider()
    st.caption("NDB dan RAN Report auto-detect mencari setiap database secara independen tanpa merge. Jika beberapa file cocok, audit memakai sumber dengan matching rows terbanyak; jika sama, snapshot terbaru. Alarm, TA dan Dump Config mempertahankan semua file yang berbeda.")

st.markdown("<div class='ran-section-label'>01 · TARGET NETWORK ELEMENT</div>", unsafe_allow_html=True)
c1,c2,c3=st.columns(3)
with c1:
    site=st.selectbox("Site Name",site_options,key="site_select")
site_ndb_parts=ndb_rows_for_site_selection(ndb_candidates, site)
enodeb_values=[]
for _ndb_path, _ndb_frame in ndb_candidates:
    if "SITE_NAME" in _ndb_frame.columns:
        _site_part=_ndb_frame[_ndb_frame["SITE_NAME"].astype(str).map(norm)==norm(site)]
        if "NE_NAME" in _site_part.columns:
            enodeb_values.extend(_site_part["NE_NAME"].tolist())
enodeb_options=unique_options(enodeb_values) or [site]
with c2:
    enodeb=st.selectbox("eNodeB Name",enodeb_options,key="enodeb_select")
alarm_sources=unique_options(alarms.get("Alarm Source",pd.Series(dtype=str)).tolist())
with c3:
    default_alarm=next((x for x in alarm_sources if norm(x)==norm(site)),alarm_sources[0] if alarm_sources else "")
    alarm_source=st.selectbox("Alarm Source",alarm_sources,index=alarm_sources.index(default_alarm) if default_alarm in alarm_sources else 0 if alarm_sources else None,
                              placeholder="No alarm source found",key="alarm_source_select",disabled=not bool(alarm_sources))

scan=st.button("⌕  RUN SITE AUDIT",type="primary",use_container_width=True)
if scan:
    with st.spinner("Running NDB/RAN, Alarm and TA analysis..."):
        ndb_path,ndb_rows,ndb_matches=detect_ndb_source(site,enodeb,selected_area)
        rat=infer_rat(enodeb,ndb_rows)
        ran_path,ran_sheet_name,ran_rows,ran_matches=detect_ran_source(site,enodeb,rat)
        cell_audit=compare_ndb_ran(ndb_rows,ran_rows,rat)
        alarm_rows=filter_alarm(alarms,alarm_source)
        # Dump Config is a read-only reference viewer. Defer its heavy workbook parsing
        # until the user explicitly opens/loads that module; core site QC should not wait for it.
        ta_rows=filter_ta(load_ta(),site,enodeb)
        ta_dates=[]
        if "Date" in ta_rows.columns:
            parsed=pd.to_datetime(ta_rows["Date"],errors="coerce")
            ta_rows=ta_rows.assign(_ParsedDate=parsed)
            ta_dates=sorted([d.strftime("%Y-%m-%d") for d in parsed.dropna().dt.date.unique()])
        ta_latest=ta_rows["_ParsedDate"].max() if "_ParsedDate" in ta_rows.columns and not ta_rows.empty else None
        coords=get_site_coordinates(ndb_rows)
        run_id=datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        manifest=newest_manifest(selected_area)
        result={
            "run_id":run_id,"area":selected_area,"site":site,"enodeb":enodeb,"alarm_source":alarm_source,"rat":rat,
            "ndb_rows":ndb_rows,"ran_rows":ran_rows,"ran_sheet":ran_sheet_name,"cell_audit":cell_audit,
            "alarm_rows":alarm_rows,"ta_rows":ta_rows,
            "ta_dates":ta_dates,"ta_latest":ta_latest,"coords":coords,"manifest":manifest,
            "ndb_path":ndb_path.name if ndb_path else None,"ran_path":ran_path.name if ran_path else None,
            "ran_matches":ran_matches,"ndb_matches":ndb_matches
        }
        st.session_state["audit_result"]=result
        # Persist concise audit history. Source files remain untouched.
        with sqlite3.connect(HISTORY_DB) as con:
            con.execute("""INSERT OR REPLACE INTO audit_runs VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (run_id,datetime.now().isoformat(timespec="seconds"),site,enodeb,alarm_source,
                 "FOUND" if not ndb_rows.empty else "NOT FOUND",cell_audit["status"],len(ndb_rows),len(ran_rows),
                 cell_audit["matched"],cell_audit["mismatch"]+cell_audit["missing"]+cell_audit["extra"],
                 len(alarm_rows),int(alarm_rows.get("Clearance Status",pd.Series(dtype=str)).astype(str).str.lower().eq("uncleared").sum()),
                 len(ta_rows),json.dumps(manifest,ensure_ascii=False)))
        migrate_schema(HISTORY_DB)
        finding_frames = [cell_audit.get("details", pd.DataFrame())]
        if not alarm_rows.empty and "Clearance Status" in alarm_rows.columns:
            uncleared_rows = alarm_rows[alarm_rows["Clearance Status"].astype(str).str.lower().eq("uncleared")].copy()
            if not uncleared_rows.empty:
                alarm_findings = pd.DataFrame({
                    "Category": "UNCLEARED ALARM",
                    "Severity": uncleared_rows.get("Severity", "Unknown"),
                    "Alarm Name": uncleared_rows.get("Name", ""),
                    "Alarm Source": uncleared_rows.get("Alarm Source", ""),
                    "MO Name": uncleared_rows.get("MO Name", ""),
                    "Clearance Status": uncleared_rows.get("Clearance Status", "")
                })
                finding_frames.append(alarm_findings)
        persist_findings(HISTORY_DB, run_id, pd.concat(finding_frames, ignore_index=True, sort=False))
        log(f"Run {run_id} | {site} | {enodeb} | {cell_audit['status']}")
    st.success(f"Scan completed · {run_id}")

res=st.session_state.get("audit_result")
if res:
    if res["site"]!=site or res["enodeb"]!=enodeb or res["alarm_source"]!=alarm_source:
        st.info("Pilihan berubah. Klik SCAN SITE untuk memperbarui hasil.")
    else:
        st.divider()
        st.markdown("<div class='ran-section-label'>02 · AUDIT WORKSPACE</div>", unsafe_allow_html=True)
        st.subheader(f"{res['site']}  ·  {res['enodeb']}")
        st.caption(f"Run ID: {res['run_id']} · Selected RAN source: {res['ran_path'] or 'Not found'} · RAT: {res['rat']}")
        if res.get("ran_matches"):
            with st.expander(f"RAN Auto Detection · {len(res['ran_matches'])} matching database(s)", expanded=True):
                st.dataframe(pd.DataFrame(res['ran_matches']), use_container_width=True, hide_index=True)
        else:
            st.warning("Site/eNodeB tidak ditemukan pada seluruh database RAN Report yang tersedia.")
        audit_tab,alarm_tab,dump_tab,ta_tab,source_tab=st.tabs([
            "① NDB vs RAN Report","② Current Alarm","③ Dump Config Viewer","④ TA Map & Distribution","⑤ Source Manifest"
        ])

        with audit_tab:
            a=res["cell_audit"]
            # Presentation-only status: derive the label from the existing audit result.
            # No NDB/RAN parsing, matching, or validation logic is changed here.
            if a["status"] == "OK":
                ndb_display, ndb_tone = "MATCHED", "success"
            elif a["status"] == "MISMATCH":
                ndb_display, ndb_tone = "MISMATCH", "error"
            elif a["status"] == "INCOMPLETE":
                ndb_display, ndb_tone = "INCOMPLETE", "warning"
            else:
                ndb_display, ndb_tone = "NOT FOUND", "error"
            col1,col2,col3,col4,col5=st.columns(5)
            col1.markdown(
                f'<div class="ran-status-metric {ndb_tone}">'
                f'<div class="ran-status-label">NDB Config</div>'
                f'<div class="ran-status-value">{ndb_display}</div>'
                f'</div>',
                unsafe_allow_html=True,
            )
            col2.metric("NDB Cells",f"{len(res['ndb_rows']):,}")
            col3.metric("RAN Cells",f"{len(res['ran_rows']):,}")
            col4.metric("Matched Cells",f"{a['matched']:,}")
            col5.metric("Findings",f"{a['mismatch']+a['missing']+a['extra']:,}")
            if a["status"]=="OK":
                st.success("NDB CONFIG OK · RAN REPORT MATCHED — seluruh cell dan parameter yang diperiksa sesuai.")
            elif a["status"]=="MISMATCH":
                st.error("NDB vs RAN REPORT MISMATCH — ditemukan cell atau parameter yang berbeda.")
            elif a["status"]=="INCOMPLETE":
                st.warning("AUDIT INCOMPLETE — data RAN Report untuk site/eNodeB ini tidak ditemukan.")
            else:
                st.error("NDB DATA NOT FOUND — site/eNodeB tidak ditemukan pada NDB.")
            st.write(f"**NDB source:** {res['ndb_path'] or 'Not found'} · **RAN sheet:** {res['ran_sheet'] or 'Not found'}")
            if res.get("ndb_matches"):
                with st.expander(f"NDB Auto Detection · {len(res['ndb_matches'])} matching database(s)", expanded=True):
                    st.dataframe(pd.DataFrame(res["ndb_matches"]), use_container_width=True, hide_index=True)
            if not a["details"].empty:
                st.dataframe(a["details"],use_container_width=True,hide_index=True)
                st.download_button("Download NDB-RAN findings CSV",a["details"].to_csv(index=False).encode("utf-8-sig"),
                                   file_name=f"{res['site']}_NDB_RAN_Findings.csv",mime="text/csv")
            else:
                st.info("Tidak ada finding mismatch pada field yang saat ini dimapping.")
            if not a["matches"].empty:
                with st.expander("View cell-by-cell comparison (including name aliases)",expanded=True):
                    st.dataframe(a["matches"],use_container_width=True,hide_index=True)
                    st.download_button("Download cell comparison CSV",a["matches"].to_csv(index=False).encode("utf-8-sig"),
                                       file_name=f"{res['site']}_Cell_Comparison.csv",mime="text/csv")
            with st.expander("View NDB reference cells"):
                st.dataframe(res["ndb_rows"],use_container_width=True,hide_index=True)
            with st.expander("View RAN Report actual cells"):
                st.dataframe(res["ran_rows"],use_container_width=True,hide_index=True)

        with alarm_tab:
            ad=res["alarm_rows"]
            if ad.empty:
                st.success(f"Tidak ada alarm untuk Alarm Source: {res['alarm_source']}")
            else:
                status_col=ad.get("Clearance Status",pd.Series("",index=ad.index)).astype(str).str.lower()
                uncleared=int(status_col.eq("uncleared").sum())
                cleared=int(status_col.eq("cleared").sum())
                critical=int(ad.get("Severity",pd.Series("",index=ad.index)).astype(str).str.lower().eq("critical").sum())
                x1,x2,x3=st.columns(3)
                x1.metric("Total Alarm",f"{len(ad):,}")
                x2.metric("Uncleared",f"{uncleared:,}")
                x3.metric("Cleared",f"{cleared:,}")
                if uncleared: st.warning(f"{uncleared} alarm masih Uncleared · Critical: {critical}")
                else: st.success("Semua alarm pada source ini berstatus Cleared.")
                cols=[c for c in ["Severity","Alarm ID","Name","Alarm Source","MO Name","Location Information",
                    "Occurrence Times","First Occurred (NT)","Last Occurred (NT)","Cleared On (NT)",
                    "Clearance Status","Acknowledgement Status","_Source File","_Source Sheet"] if c in ad.columns]
                st.dataframe(ad[cols],use_container_width=True,hide_index=True)
                st.download_button("Download alarm details CSV",ad[cols].to_csv(index=False).encode("utf-8-sig"),
                                   file_name=f"{res['alarm_source']}_Alarm_Details.csv",mime="text/csv")

        with dump_tab:
            render_dump_explorer(res["site"],res["enodeb"],res["run_id"])

        with ta_tab:
            td=res["ta_rows"]
            if td.empty:
                st.warning("Data TA untuk eNodeB/site ini tidak ditemukan pada seluruh file TA.")
            else:
                if res["ta_dates"]:
                    latest_date=td["_ParsedDate"].max().strftime("%Y-%m-%d")
                    date_options=res["ta_dates"]
                    default_idx=date_options.index(latest_date) if latest_date in date_options else len(date_options)-1
                    chosen_date=st.selectbox("TA Date",date_options,index=default_idx,key=f"ta_date_{res['run_id']}")
                    chosen=pd.to_datetime(chosen_date)
                    td=td[td["_ParsedDate"].dt.strftime("%Y-%m-%d")==chosen_date].copy()
                else:
                    st.warning("Kolom Date tidak bisa diparse; menampilkan seluruh data yang cocok.")
                bins=[f"{TA_PREFIX}{i}" for i in range(12)]
                available=[c for c in bins if c in td.columns]
                if not available:
                    st.error("Kolom TA Index0–11 tidak ditemukan.")
                else:
                    for c in available: td[c]=pd.to_numeric(td[c],errors="coerce").fillna(0)
                    agg=td[available].sum()
                    total=float(agg.sum())
                    pct=agg/total*100 if total else agg*0
                    chart=pd.DataFrame({"TA Index":[f"Index {i}" for i in range(12)],
                                        "UE/MR Count":[float(agg.get(f"{TA_PREFIX}{i}",0)) for i in range(12)],
                                        "Percentage":[float(pct.get(f"{TA_PREFIX}{i}",0)) for i in range(12)]})
                    m1,m2,m3=st.columns(3)
                    m1.metric("TA Records",f"{len(td):,}")
                    m2.metric("Total TA Count",f"{int(total):,}")
                    m3.metric("Cells",f"{td['Cell Name'].nunique():,}" if "Cell Name" in td.columns else "N/A")
                    fig=px.bar(chart,x="TA Index",y="UE/MR Count",hover_data={"Percentage":":.2f"},
                               title="TA Distribution — Aggregated by selected site/eNodeB")
                    fig.update_layout(height=390,xaxis_title="TA Index",yaxis_title="Count")
                    st.plotly_chart(fig,use_container_width=True)
                    fig2=px.line(chart,x="TA Index",y="Percentage",markers=True,title="TA Distribution Percentage")
                    fig2.update_layout(height=300,yaxis_title="Percentage (%)")
                    st.plotly_chart(fig2,use_container_width=True)
                    st.dataframe(chart,use_container_width=True,hide_index=True)
                    st.subheader("TA Map View")
                    coords=res["coords"]
                    if coords:
                        step=st.number_input("TA bin distance step (meter)",min_value=1.0,max_value=500.0,value=78.125,step=1.0,
                                              help="Default nominal LTE timing-advance distance step. Adjust if your Huawei KPI bin definition differs.")
                        st.caption("Map displays concentric distance reference rings centered on NDB site coordinates. It does not represent individual UE GPS positions or sector azimuth.")
                        try:
                            from streamlit_folium import st_folium
                            fmap=make_ta_map(coords[0],coords[1],agg.to_dict(),step)
                            st_folium(fmap,use_container_width=True,height=560,returned_objects=[])
                        except Exception as e:
                            st.error(f"Map component unavailable: {e}. Install streamlit-folium and folium.")
                    else:
                        st.warning("Koordinat longitude/latitude site tidak ditemukan di NDB. TA chart tetap tersedia, tetapi peta tidak bisa diposisikan.")
                    display_cols=[c for c in ["Date","eNodeB Name","eNodeB Function Name","Cell Name","LocalCell Id","Frequency band"]+available if c in td.columns]
                    st.subheader("TA per Cell")
                    st.dataframe(td[display_cols],use_container_width=True,hide_index=True)
                    st.download_button("Download TA filtered CSV",td[display_cols].to_csv(index=False).encode("utf-8-sig"),
                                       file_name=f"{res['site']}_TA_Distribution.csv",mime="text/csv")

        with source_tab:
            st.subheader("Audit source manifest")
            st.json(res["manifest"])
            st.caption("NDB uses latest snapshot per area. RAN Report searches all independent workbooks and selects one matching source; source databases are never merged. Alarm, TA and Dump Config retain their existing multi-file behavior.")


# ---------------------------- V3.6 advanced QC modules ----------------------------
migrate_schema(HISTORY_DB)
st.divider()
st.header("V3.6 · Advanced QC Workspace")
adv_tabs = st.tabs(["① Compliance Score", "② Multi-Site Scan", "③ Alarm Intelligence", "④ TA Insight", "⑤ Site Configuration Map", "⑥ Historical Audit", "⑦ QC Approval & Reports"])

with adv_tabs[0]:
    if res:
        cm = compliance_metrics(res["cell_audit"])
        c1,c2,c3,c4 = st.columns(4)
        c1.metric("Parameter Compliance", f"{cm['parameter_compliance_pct']:.2f}%" if cm['parameter_compliance_pct'] is not None else "N/A")
        c2.metric("Cell Match Rate", f"{cm['cell_match_rate_pct']:.2f}%")
        c3.metric("Matched Checks", f"{cm['matched_checks']:,}")
        c4.metric("Mismatch Checks", f"{cm['mismatched_checks']:,}")
        st.caption("Parameter compliance counts only mapped fields with a value on both sides. Missing/extra cells and duplicate identities are reported separately.")
        st.dataframe(pd.DataFrame([
            {"Metric":"Matched parameter checks","Value":cm['matched_checks']},
            {"Metric":"Mismatched parameter checks","Value":cm['mismatched_checks']},
            {"Metric":"Missing cells","Value":cm['missing_cells']},
            {"Metric":"Extra cells","Value":cm['extra_cells']},
            {"Metric":"Duplicate identity findings","Value":cm['duplicate_findings']},
        ]), use_container_width=True, hide_index=True)
    else:
        st.info("Run SCAN SITE first to calculate compliance metrics.")

with adv_tabs[1]:
    st.markdown("**Batch scan sites from the selected NDB Area.** Each site/eNodeB is audited independently; one failed item does not stop the batch.")
    batch_sites = st.multiselect("Select sites for batch scan", site_options, key="v36_batch_sites")
    if st.button("▶ RUN MULTI-SITE SCAN", type="primary", disabled=not batch_sites, key="v36_batch_scan"):
        batch_id = datetime.now().strftime("BATCH_%Y%m%d_%H%M%S_%f")
        batch_rows=[]; failures=[]
        progress = st.progress(0, text="Preparing batch...")
        for idx, batch_site in enumerate(batch_sites, start=1):
            try:
                site_rows_parts = ndb_rows_for_site_selection(ndb_candidates, batch_site)
                ne_values=[]
                for _ndb_path, _ndb_frame in ndb_candidates:
                    _site_part=_ndb_frame[_ndb_frame["SITE_NAME"].astype(str).map(norm)==norm(batch_site)]
                    if "NE_NAME" in _site_part.columns:
                        ne_values.extend(_site_part["NE_NAME"].tolist())
                ne_list = unique_options(ne_values) or [batch_site]
                for batch_ne in ne_list:
                    b_ndb_path, b_ndb_rows, b_ndb_matches = detect_ndb_source(batch_site, batch_ne, selected_area)
                    brat = infer_rat(batch_ne, b_ndb_rows)
                    b_ran_path, b_sheet, b_ran_rows, b_ran_matches = detect_ran_source(batch_site, batch_ne, brat)
                    ba = compare_ndb_ran(b_ndb_rows, b_ran_rows, brat)
                    b_alarm_source = next((x for x in alarm_sources if norm(x)==norm(batch_site)), alarm_source)
                    b_alarm_rows = filter_alarm(alarms, b_alarm_source)
                    bcm = compliance_metrics(ba)
                    batch_rows.append({"Site Name":batch_site,"eNodeB Name":batch_ne,"RAT":brat,
                        "Audit Status":ba["status"],"NDB Source":b_ndb_path.name if b_ndb_path else "Not found",
                        "NDB Matching Databases":len(b_ndb_matches),"RAN Source":b_ran_path.name if b_ran_path else "Not found",
                        "RAN Matching Databases":len(b_ran_matches),"NDB Cells":len(b_ndb_rows),"RAN Cells":len(b_ran_rows),
                        "Matched Cells":ba["matched"],"Mismatch Checks":ba["mismatch"],
                        "Missing Cells":ba["missing"],"Extra Cells":ba["extra"],
                        "Parameter Compliance (%)":bcm["parameter_compliance_pct"],
                        "Alarm Source":b_alarm_source,"Total Alarms":len(b_alarm_rows),
                        "Uncleared Alarms":int(b_alarm_rows.get("Clearance Status",pd.Series(dtype=str)).astype(str).str.lower().eq("uncleared").sum())})
            except Exception as exc:
                failures.append({"Site Name":batch_site,"Error":str(exc)})
            progress.progress(idx/len(batch_sites), text=f"Processed {idx}/{len(batch_sites)} selected sites")
        batch_df=pd.DataFrame(batch_rows)
        st.session_state["v36_batch_result"]={"batch_id":batch_id,"area":selected_area,"data":batch_df,"failures":failures}
        with sqlite3.connect(HISTORY_DB) as con:
            con.execute("INSERT OR REPLACE INTO multi_site_batches(batch_id,created_at,area,selected_sites,completed,failed,result_json) VALUES(?,?,?,?,?,?,?)",
                (batch_id,datetime.now().isoformat(timespec="seconds"),selected_area,json.dumps(batch_sites),len(batch_rows),len(failures),batch_df.to_json(orient="records")))
        st.success(f"Batch scan finished · {batch_id} · {len(batch_rows)} audit item(s) · {len(failures)} failure(s)")
    batch_res=st.session_state.get("v36_batch_result")
    if batch_res:
        st.caption(f"Batch ID: {batch_res['batch_id']} · Area: {batch_res['area']}")
        if not batch_res["data"].empty:
            st.dataframe(batch_res["data"],use_container_width=True,hide_index=True)
            st.download_button("Download Multi-Site Summary CSV",batch_res["data"].to_csv(index=False).encode("utf-8-sig"),
                file_name=f"{batch_res['batch_id']}_summary.csv",mime="text/csv")
        if batch_res["failures"]:
            st.warning("Some sites could not be scanned")
            st.dataframe(pd.DataFrame(batch_res["failures"]),use_container_width=True,hide_index=True)

with adv_tabs[2]:
    if res:
        alarm_stats=alarm_summary(res["alarm_rows"])
        q1,q2,q3=st.columns(3)
        q1.metric("Total Alarms",f"{alarm_stats['total']:,}")
        q2.metric("Cleared",f"{alarm_stats['cleared']:,}")
        q3.metric("Uncleared",f"{alarm_stats['uncleared']:,}")
        if alarm_stats["severity"]:
            sev_df=pd.DataFrame([{"Severity":k,"Count":v} for k,v in alarm_stats["severity"].items()])
            st.plotly_chart(px.bar(sev_df,x="Severity",y="Count",title="Alarm Severity Distribution"),use_container_width=True)
            st.dataframe(sev_df,use_container_width=True,hide_index=True)
        st.caption("Alarm impact association is limited to the selected Alarm Source and available MO/Cell fields. No causal network impact is inferred automatically.")
    else:
        st.info("Run SCAN SITE first to inspect alarm intelligence.")

with adv_tabs[3]:
    if res:
        default_step=78.125
        step_m=st.number_input("TA bin step (meter)",min_value=1.0,max_value=500.0,value=default_step,step=1.0,key="v36_ta_step")
        ta_for_insight=res["ta_rows"].copy()
        if not ta_for_insight.empty and "_ParsedDate" in ta_for_insight.columns:
            latest_ta_date=ta_for_insight["_ParsedDate"].max()
            if pd.notna(latest_ta_date):
                ta_for_insight=ta_for_insight[ta_for_insight["_ParsedDate"].dt.date==latest_ta_date.date()].copy()
        ta_table,ta_stats=ta_summary(ta_for_insight,step_m)
        t1,t2,t3=st.columns(3)
        t1.metric("TA Total Count",f"{ta_stats['total']:,}")
        t2.metric("Dominant Index",str(ta_stats["dominant_index"]) if ta_stats["dominant_index"] is not None else "N/A")
        t3.metric("P90 Estimate",f"{ta_stats['percentiles_m'].get('P90')} m" if ta_stats["percentiles_m"] else "N/A")
        if not ta_table.empty:
            st.plotly_chart(px.bar(ta_table,x="TA Index",y="Count",hover_data=["Percentage","Distance Midpoint (m)"],title="TA Count by Index"),use_container_width=True)
            st.plotly_chart(px.line(ta_table,x="TA Index",y="Percentage",markers=True,title="TA Percentage by Index"),use_container_width=True)
            st.dataframe(ta_table,use_container_width=True,hide_index=True)
            st.json(ta_stats["percentiles_m"])
        st.caption("Percentile distances are histogram-bin estimates using the configured step, not UE GPS positions. Confirm bin definition with the applicable vendor/operator KPI specification.")
    else:
        st.info("Run SCAN SITE first to calculate TA insight.")

with adv_tabs[4]:
    if res:
        coords=res.get("coords")
        if coords:
            try:
                import folium
                from streamlit_folium import st_folium
                fmap=folium.Map(location=[coords[0],coords[1]],zoom_start=16,control_scale=True)
                folium.Marker([coords[0],coords[1]],tooltip=f"{res['site']} · NDB coordinate").add_to(fmap)
                az_col=next((c for c in ["AZIMUTH","AZIMUTH_DEG","ANTENNA_AZIMUTH","BEARING"] if c in res["ndb_rows"].columns),None)
                bw_col=next((c for c in ["BEAMWIDTH","BEAM_WIDTH"] if c in res["ndb_rows"].columns),None)
                radius_col=next((c for c in ["RADIUS_METER","RADIUS_METERS","RADIUS"] if c in res["ndb_rows"].columns),None)
                if az_col:
                    import math
                    def dest_point(lat,lon,bearing,distance):
                        R=6371000.0; br=math.radians(float(bearing)); d=float(distance)/R
                        la1=math.radians(lat); lo1=math.radians(lon)
                        la2=math.asin(math.sin(la1)*math.cos(d)+math.cos(la1)*math.sin(d)*math.cos(br))
                        lo2=lo1+math.atan2(math.sin(br)*math.sin(d)*math.cos(la1),math.cos(d)-math.sin(la1)*math.sin(la2))
                        return [math.degrees(la2),math.degrees(lo2)]
                    drawn=0
                    for _,sr in res["ndb_rows"].iterrows():
                        try:
                            az=float(sr[az_col]); bw=float(sr[bw_col]) if bw_col else 65.0
                            rad=float(sr[radius_col]) if radius_col else 500.0
                            pts=[[coords[0],coords[1]]]
                            for deg in [az-bw/2+i*bw/20 for i in range(21)]: pts.append(dest_point(coords[0],coords[1],deg,rad))
                            pts.append([coords[0],coords[1]])
                            folium.Polygon(pts,tooltip=f"{sr.get('CELL_NAME','Cell')} · Azimuth {az:.1f}° · Beamwidth {bw:.1f}°",fill=True,fill_opacity=0.12).add_to(fmap)
                            drawn+=1
                        except Exception: continue
                    st.caption(f"Sector wedges drawn: {drawn} · source azimuth field: {az_col}. Missing beamwidth/radius uses illustrative defaults; review before RF conclusions.")
                else:
                    st.info("NDB does not contain a recognized azimuth column. Showing site pin only; no sector direction is invented.")
                st_folium(fmap,use_container_width=True,height=580,returned_objects=[])
                st.caption("Map location comes from NDB longitude/latitude. Sector wedges are shown only when an azimuth field exists.")
            except Exception as exc:
                st.error(f"Map rendering failed: {exc}")
        else:
            st.warning("Valid longitude/latitude are not available in the selected NDB rows.")
    else:
        st.info("Run SCAN SITE first to display the site map.")

with adv_tabs[5]:
    try:
        with sqlite3.connect(HISTORY_DB) as con:
            hist=pd.read_sql_query("SELECT run_id,scanned_at,site_name,enodeb_name,ran_status,ndb_cells,ran_cells,matched_cells,mismatch_cells,alarm_rows,uncleared_alarms,ta_rows FROM audit_runs ORDER BY scanned_at DESC LIMIT 500",con)
        st.dataframe(hist,use_container_width=True,hide_index=True)
        if not hist.empty:
            run_ids=hist["run_id"].astype(str).tolist()
            compare_ids=st.multiselect("Select two audit runs for historical comparison",run_ids,max_selections=2,key="v36_hist_compare")
            if len(compare_ids)==2:
                left=hist[hist.run_id==compare_ids[0]].iloc[0]
                right=hist[hist.run_id==compare_ids[1]].iloc[0]
                diff=[]
                for col in ["matched_cells","mismatch_cells","uncleared_alarms","ta_rows"]:
                    diff.append({"Metric":col,"Run A":int(left[col]),"Run B":int(right[col]),"Delta (B-A)":int(right[col])-int(left[col])})
                st.subheader("Historical Delta")
                st.dataframe(pd.DataFrame(diff),use_container_width=True,hide_index=True)
    except Exception as exc:
        st.warning(f"Historical audit unavailable: {exc}")

with adv_tabs[6]:
    if res:
        cm=compliance_metrics(res["cell_audit"])
        al=alarm_summary(res["alarm_rows"])
        report_ta_rows=res["ta_rows"].copy()
        if not report_ta_rows.empty and "_ParsedDate" in report_ta_rows.columns:
            latest_ta_date=report_ta_rows["_ParsedDate"].max()
            if pd.notna(latest_ta_date):
                report_ta_rows=report_ta_rows[report_ta_rows["_ParsedDate"].dt.date==latest_ta_date.date()].copy()
        ta_table,ta_stats=ta_summary(report_ta_rows,float(st.session_state.get("v36_ta_step",78.125)))
        current_approval=latest_approval(HISTORY_DB,res["run_id"])
        st.markdown(f"**Audit Run:** `{res['run_id']}` · **Current approval:** `{current_approval[1] if current_approval else 'PENDING'}`")
        with st.form(f"approval_form_{res['run_id']}"):
            reviewer=st.text_input("Reviewer name",placeholder="Enter reviewer name")
            approval_status=st.selectbox("Decision",["APPROVED","REJECTED","NEEDS REVISION"])
            approval_remarks=st.text_area("QC remarks",placeholder="Review notes / corrective action")
            submit_approval=st.form_submit_button("Save QC Approval",type="primary")
        if submit_approval:
            try:
                save_approval(HISTORY_DB,res["run_id"],reviewer,approval_status,approval_remarks)
                st.success("QC approval saved to audit history.")
                st.rerun()
            except Exception as exc:
                st.error(str(exc))
        current_approval=latest_approval(HISTORY_DB,res["run_id"])
        approved=bool(current_approval and current_approval[1]=="APPROVED")
        st.divider()
        st.markdown("**Final Report Generation** — available only after manual approval.")
        if st.button("GENERATE EXCEL + PDF REPORT",type="primary",disabled=not approved,key=f"gen_report_{res['run_id']}"):
            try:
                manifest=res.get("manifest",{})
                report_result=dict(res)
                report_result["ta_rows"]=report_ta_rows
                excel_bytes=build_excel_report(report_result,cm,al,ta_table,ta_stats,current_approval,manifest)
                pdf_bytes=build_pdf_report(res,cm,al,ta_stats,current_approval)
                safe_site=re.sub(r"[^A-Za-z0-9_-]+","_",str(res["site"]))
                out_dir=OUT_ROOT / safe_site
                out_dir.mkdir(parents=True,exist_ok=True)
                report_id=datetime.now().strftime("RPT_%Y%m%d_%H%M%S_%f")
                xname=f"{safe_site}_{report_id}.xlsx"; pname=f"{safe_site}_{report_id}.pdf"
                (out_dir/xname).write_bytes(excel_bytes); (out_dir/pname).write_bytes(pdf_bytes)
                with sqlite3.connect(HISTORY_DB) as con:
                    con.execute("INSERT INTO report_history VALUES(?,?,?,?,?,?)",(report_id,res["run_id"],"EXCEL",xname,datetime.now().isoformat(timespec="seconds"),current_approval[1]))
                    con.execute("INSERT INTO report_history VALUES(?,?,?,?,?,?)",(report_id+"_PDF",res["run_id"],"PDF",pname,datetime.now().isoformat(timespec="seconds"),current_approval[1]))
                    con.commit()
                st.session_state[f"report_excel_{res['run_id']}"]=excel_bytes
                st.session_state[f"report_pdf_{res['run_id']}"]=pdf_bytes
                st.success(f"Reports generated and saved in output_Concheck/{safe_site}/")
            except Exception as exc:
                st.error(f"Report generation failed: {exc}")
        xb=st.session_state.get(f"report_excel_{res['run_id']}")
        pb=st.session_state.get(f"report_pdf_{res['run_id']}")
        if xb and pb:
            c1,c2=st.columns(2)
            c1.download_button("Download Excel QC Report",xb,file_name=f"{res['site']}_{res['run_id']}_QC.xlsx",mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
            c2.download_button("Download PDF QC Report",pb,file_name=f"{res['site']}_{res['run_id']}_QC.pdf",mime="application/pdf")
        if not approved:
            st.info("Approve the current audit run before generating final Excel/PDF reports.")
    else:
        st.info("Run SCAN SITE first to access QC approval and report generation.")

st.divider()
st.caption("Source database files are read-only. Audit history is stored in database/concheck_history.db. No source workbook or CSV is modified.")
