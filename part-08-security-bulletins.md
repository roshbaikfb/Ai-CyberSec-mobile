[← الجزء السابع](./part-07-patch-mining.md) · [الفهرس](./README.md)

# الجزء الثامن: Android Security Bulletins

## الفصل 18: Bulletin Collector

الـSecurity Patch Mining (الجزء السابع) يعطينا candidates من تاريخ Git وحده — بدون معرفة أي CVE، severity، أو أي إصدارات Android تأثرت رسميًا. هذا الفصل يضيف طبقة ربط خارجية: **Android Security Bulletins (ASB)** الرسمية، التي تنشرها Google شهريًا وتحتوي روابط لـCVEs ومكوّناتها وseverity وAOSP commits المرتبطة (حين تكون متاحة).

### 18.1 لماذا هذه الطبقة منفصلة عن Patch Mining

| المصدر | ماذا يعطينا | ماذا لا يعطينا |
|---|---|---|
| Git history (الجزء السابع) | كل commit فعليًا حدث، بصرف النظر عن التوثيق الرسمي | لا يخبرنا severity، ولا CVE ID، ولا الإصدارات المتأثرة رسميًا |
| Android Security Bulletins | CVE ID، severity، المكوّن المتأثر، الإصدارات، وأحيانًا رابط commit مباشر | **لا تغطي كل الإصلاحات الأمنية** — كثير من الـhardening fixes لا تُرفَع لمستوى CVE منشور |

الاستنتاج المهم: **لا نفترض أبدًا أن كل CVE له commit واضح في السجل العام**، ولا العكس (commit أمني مهم دون CVE مقابل). الطبقتان متكاملتان وليستا بديلتين لبعضهما.

### 18.2 نموذج البيانات (Data Model)

```json
{
  "cve_id": "CVE-2023-XXXXX",
  "bulletin_date": "2023-11-01",
  "severity": "High",
  "component": "Framework",
  "affected_versions": ["11", "12", "12L", "13"],
  "aosp_references": [
    {
      "url": "https://android.googlesource.com/platform/frameworks/base/+/abcdef123456",
      "commit_hash": "abcdef123456",
      "resolved": true
    }
  ],
  "description_summary": "Elevation of privilege vulnerability in ...",
  "source_bulletin_url": "https://source.android.com/docs/security/bulletin/2023-11-01"
}
```

الحقل `resolved` مهم: بعض الروابط المنشورة في الـBulletin تكون لصفحات Gerrit غير عامة الوصول أو تُغلَق لاحقًا — نحتاج نُسجّل بصراحة هل استطعنا فعلاً الوصول للـcommit المقابل أم لا، بدل افتراض النجاح.

### 18.3 `bulletin_collector/fetch_bulletins.py`

```python
# bulletin_collector/fetch_bulletins.py
"""
يجلب صفحات Android Security Bulletin من source.android.com،
ويستخرج جدول الـCVEs ومكوّناتها وروابط AOSP المرتبطة إن وُجدت.

ملاحظة: بنية صفحات الـBulletin قد تتغير بمرور الوقت (HTML structure)،
لذلك هذا السكريبت يعتمد على parsing مرن مع تسجيل صريح لأي صف
تعذّر تفسيره، بدل تجاهله بصمت.
"""
import re
import json
import time
from pathlib import Path
from dataclasses import dataclass, asdict
from urllib.request import urlopen, Request
from html.parser import HTMLParser

BULLETIN_INDEX_URL = "https://source.android.com/docs/security/bulletin/asb-overview"

@dataclass
class BulletinEntry:
    cve_id: str
    bulletin_date: str
    severity: str
    component: str
    affected_versions: list[str]
    aosp_commit_urls: list[str]
    source_bulletin_url: str
    parse_warning: str | None = None

def fetch_html(url: str, retries: int = 3, delay: float = 2.0) -> str:
    last_err = None
    for attempt in range(retries):
        try:
            req = Request(url, headers={"User-Agent": "afvrm-research/0.1"})
            with urlopen(req, timeout=30) as resp:
                return resp.read().decode("utf-8", errors="replace")
        except Exception as e:
            last_err = e
            time.sleep(delay * (attempt + 1))
    raise RuntimeError(f"Failed to fetch {url} after {retries} attempts: {last_err}")

class BulletinTableParser(HTMLParser):
    """
    Parser مبسّط لجداول الـCVE في صفحة bulletin واحدة.
    يفترض بنية <table> قياسية بأعمدة: CVE | References | Type | Severity |
    Updated AOSP versions.
    هذه البنية قد تتغير — أي صف لا يطابق التوقعات يُسجَّل كـparse_warning
    بدل أن يُفشل السكريبت بالكامل.
    """
    def __init__(self, bulletin_date: str, bulletin_url: str):
        super().__init__()
        self.bulletin_date = bulletin_date
        self.bulletin_url = bulletin_url
        self.entries: list[BulletinEntry] = []
        self._in_row = False
        self._current_cells: list[str] = []
        self._current_text = ""
        self._current_links: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag == "tr":
            self._in_row = True
            self._current_cells = []
        if tag == "td":
            self._current_text = ""
            self._current_links = []
        if tag == "a" and self._in_row:
            href = dict(attrs).get("href", "")
            if href:
                self._current_links.append(href)

    def handle_data(self, data):
        if self._in_row:
            self._current_text += data.strip()

    def handle_endtag(self, tag):
        if tag == "td":
            self._current_cells.append({
                "text": self._current_text.strip(),
                "links": list(self._current_links),
            })
        if tag == "tr":
            self._in_row = False
            self._process_row(self._current_cells)

    def _process_row(self, cells: list[dict]):
        if len(cells) < 4:
            return  # ليس صف بيانات فعلي (على الأرجح header أو فارغ)

        cve_text = cells[0]["text"]
        if not re.match(r"CVE-\d{4}-\d+", cve_text):
            return

        try:
            severity = cells[2]["text"] if len(cells) > 2 else "Unknown"
            component = cells[3]["text"] if len(cells) > 3 else "Unknown"
            versions_text = cells[4]["text"] if len(cells) > 4 else ""
            versions = [v.strip() for v in versions_text.split(",") if v.strip()]

            aosp_links = [
                link for link in cells[1]["links"]
                if "googlesource.com" in link
            ]

            self.entries.append(BulletinEntry(
                cve_id=cve_text,
                bulletin_date=self.bulletin_date,
                severity=severity,
                component=component,
                affected_versions=versions,
                aosp_commit_urls=aosp_links,
                source_bulletin_url=self.bulletin_url,
            ))
        except Exception as e:
            self.entries.append(BulletinEntry(
                cve_id=cve_text,
                bulletin_date=self.bulletin_date,
                severity="Unknown",
                component="Unknown",
                affected_versions=[],
                aosp_commit_urls=[],
                source_bulletin_url=self.bulletin_url,
                parse_warning=str(e),
            ))

def parse_bulletin_page(bulletin_date: str, bulletin_url: str) -> list[BulletinEntry]:
    html = fetch_html(bulletin_url)
    parser = BulletinTableParser(bulletin_date, bulletin_url)
    parser.feed(html)
    return parser.entries

def extract_commit_hash(gerrit_url: str) -> str | None:
    match = re.search(r"/\+/([0-9a-f]{6,40})", gerrit_url)
    return match.group(1) if match else None

def collect_bulletins(bulletin_urls: dict[str, str], output_path: Path):
    """bulletin_urls: {'2023-11-01': 'https://source.android.com/.../2023-11-01'}"""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    total = 0
    warnings = 0
    with output_path.open("w") as f:
        for date, url in bulletin_urls.items():
            print(f"Fetching bulletin: {date}")
            try:
                entries = parse_bulletin_page(date, url)
            except Exception as e:
                print(f"  FAILED to fetch/parse {url}: {e}")
                continue
            for entry in entries:
                d = asdict(entry)
                d["resolved_commits"] = [
                    extract_commit_hash(u) for u in entry.aosp_commit_urls
                ]
                f.write(json.dumps(d, ensure_ascii=False) + "\n")
                total += 1
                if entry.parse_warning:
                    warnings += 1
            time.sleep(1.0)  # لطف تجاه الخادم
    print(f"Done: {total} CVE entries written ({warnings} with parse warnings) "
          f"to {output_path}")

if __name__ == "__main__":
    # مثال — قائمة روابط bulletin فعلية يجب تحديثها من الفهرس الرسمي
    example_bulletins = {
        "2023-11-01": "https://source.android.com/docs/security/bulletin/2023-11-01",
        "2023-12-01": "https://source.android.com/docs/security/bulletin/2023-12-01",
    }
    collect_bulletins(
        example_bulletins,
        Path("bulletin_collector/output/bulletins.jsonl"),
    )
```

> **تنبيه على هشاشة الـHTML parsing:** صفحات `source.android.com` تُعاد هيكلتها بمرور الوقت. هذا الـParser مبني ليكون **متسامحًا** (يسجّل `parse_warning` بدل الانهيار)، لكن يجب مراجعة عينة من المخرجات يدويًا بعد كل تشغيل للتأكد أن الأعمدة (severity, component, versions) لا تزال في نفس الترتيب المفترَض. لو تغيّرت بنية الصفحة رسميًا، عدّل فهارس `cells[N]` تبعًا لذلك.

### 18.4 ربط الـBulletins بـcommits الجزء السابع

```python
# bulletin_collector/link_to_patch_mining.py
"""
يربط CVE entries بـcommits المستخرجة سابقًا في before_after.jsonl
(الفصل 17)، عبر مطابقة commit_hash إن وُجد، أو عبر مطابقة تقريبية
بالتاريخ والملفات المتأثرة كخطة بديلة عند غياب الرابط المباشر.
"""
import json
from pathlib import Path
from collections import defaultdict

def load_before_after(path: Path) -> dict[str, dict]:
    index = {}
    with path.open() as f:
        for line in f:
            pair = json.loads(line)
            index[pair["commit_hash"]] = pair
    return index

def load_bulletins(path: Path) -> list[dict]:
    with path.open() as f:
        return [json.loads(line) for line in f]

def link(before_after_path: Path, bulletins_path: Path, output_path: Path):
    ba_index = load_before_after(before_after_path)
    bulletins = load_bulletins(bulletins_path)

    matched = 0
    unmatched: list[dict] = []

    with output_path.open("w") as f:
        for bulletin in bulletins:
            found_pair = None
            for commit_hash in bulletin.get("resolved_commits", []):
                if not commit_hash:
                    continue
                # مطابقة بادئة الهاش لأن روابط Gerrit أحيانًا مختصرة
                for full_hash, pair in ba_index.items():
                    if full_hash.startswith(commit_hash):
                        found_pair = pair
                        break
                if found_pair:
                    break

            if found_pair:
                matched += 1
                record = {
                    "cve_id": bulletin["cve_id"],
                    "severity": bulletin["severity"],
                    "component": bulletin["component"],
                    "commit_hash": found_pair["commit_hash"],
                    "file_path": found_pair["file_path"],
                    "linked": True,
                }
            else:
                unmatched.append(bulletin)
                record = {
                    "cve_id": bulletin["cve_id"],
                    "severity": bulletin["severity"],
                    "component": bulletin["component"],
                    "commit_hash": None,
                    "file_path": None,
                    "linked": False,
                }
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    print(f"Matched: {matched} / {len(bulletins)} bulletins linked to a "
          f"local before/after pair")
    print(f"Unmatched: {len(unmatched)} — these CVEs have no local commit "
          f"match (expected; not every CVE resolves publicly)")

if __name__ == "__main__":
    link(
        before_after_path=Path("patch_miner/output/android-14_before_after.jsonl"),
        bulletins_path=Path("bulletin_collector/output/bulletins.jsonl"),
        output_path=Path("bulletin_collector/output/linked_cves.jsonl"),
    )
```

### 18.5 لماذا "غير المرتبط" له قيمة أيضًا

عدم وجود تطابق بين CVE وcommit محلي **ليس فشلًا في السكريبت** — هذا متوقَّع ومهم لسببين:

1. بعض CVEs تُصلَح في مستودعات غير `frameworks/base` (native code, HAL, drivers مخصصة لمصنّعين) وهي خارج نطاق المشروع في v0.1.
2. بعض الروابط في الـBulletin تشير لأنظمة داخلية غير عامة الوصول (internal Gerrit instances).

القائمة غير المرتبطة (`linked: false`) تُحفَظ كسجل — قد تُستخدم لاحقًا كمرشحين للبحث اليدوي، أو لتوسيع نطاق الـcollector (الجزء السادس، القسم 4.2) خارج `frameworks/base` عند الحاجة.

> **Definition of Done — الجزء الثامن:** يوجد ملف `linked_cves.jsonl` ناتج فعليًا من تشغيل السكريبت على الأقل على bulletin واحد حقيقي، مع نسبة ربط معقولة (ولو منخفضة — 10-30% أمر متوقَّع وليس خطأً)، وقائمة واضحة بالـCVEs غير المرتبطة محفوظة للمراجعة اللاحقة بدل حذفها.

---

[← الجزء السابع](./part-07-patch-mining.md) · [الفهرس](./README.md) · [الجزء التاسع →](./part-09-parsing.md)
