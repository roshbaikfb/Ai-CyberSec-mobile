[← الجزء السابع عشر](./part-17-provenance.md) · [الفهرس](./README.md)

# الجزء الثامن عشر: Deduplication

## الفصل 35: Duplicate Detection

بحلول هذه المرحلة، لدينا عينات من مصادر متعددة (Vulnerable/Fixed pairs، Hard Negatives، Crafted insufficient-context) وعبر عدة إصدارات Android. **التكرار غير المُكتشَف هو أخطر تهديد لصحة الـBenchmark لاحقًا** — عينة شبه متطابقة تظهر في Train وTest تعطي انطباعًا كاذبًا بأن النموذج "تعلّم" بينما هو فعليًا "حفظ".

### 35.1 أربع طبقات كشف، من الأصرم للأكثر مرونة

| الطبقة | تكتشف ماذا | التكلفة الحسابية |
|---|---|---|
| **Exact hash** | نسخ حرفية متطابقة 100% (نفس method نُسخت لعدة ملفات، أو نفس الكود عبر إصدارات لم تتغير) | زهيدة جدًا |
| **Normalized code hash** | تطابق بعد إزالة whitespace/comments (نفس المنطق، تنسيق مختلف) | زهيدة |
| **MinHash (Locality-Sensitive Hashing)** | تشابه نصي عالٍ لكن غير متطابق (نفس method مع تعديل بسيط في تسمية متغير) | متوسطة، تتوسع جيدًا لآلاف السجلات |
| **AST similarity** | تشابه بنيوي حتى مع اختلاف نصي أكبر (إعادة ترتيب أسطر، تغيير أسماء كامل) | الأعلى تكلفة — نستخدمها فقط على مرشحين مرشَّحين مسبقًا من MinHash |

القرار: نطبّق الطبقات بالترتيب — كل طبقة تُصفّي عبء العمل عن التالية، بدل تشغيل AST comparison على كل زوج ممكن (وهو غير عملي حسابيًا لآلاف العينات).

### 35.2 `dedup/exact_and_normalized.py`

```python
# dedup/exact_and_normalized.py
import hashlib
import re
import json
from pathlib import Path
from collections import defaultdict

def normalize_source(source: str) -> str:
    no_comments = re.sub(r"//.*", "", source)
    no_comments = re.sub(r"/\*.*?\*/", "", no_comments, flags=re.DOTALL)
    return re.sub(r"\s+", " ", no_comments).strip()

def exact_hash(source: str) -> str:
    return hashlib.sha256(source.encode("utf8")).hexdigest()

def normalized_hash(source: str) -> str:
    return hashlib.sha256(normalize_source(source).encode("utf8")).hexdigest()

def find_exact_and_normalized_duplicates(samples_jsonl: Path) -> dict:
    exact_groups: dict[str, list[str]] = defaultdict(list)
    normalized_groups: dict[str, list[str]] = defaultdict(list)

    with samples_jsonl.open() as f:
        for line in f:
            sample = json.loads(line)
            source = sample["code_context"]["current_method"]
            sid = sample["sample_id"]
            exact_groups[exact_hash(source)].append(sid)
            normalized_groups[normalized_hash(source)].append(sid)

    exact_dups = {h: ids for h, ids in exact_groups.items() if len(ids) > 1}
    normalized_dups = {
        h: ids for h, ids in normalized_groups.items() if len(ids) > 1
    }

    return {
        "exact_duplicate_groups": len(exact_dups),
        "exact_duplicate_samples": sum(len(v) for v in exact_dups.values()),
        "normalized_duplicate_groups": len(normalized_dups),
        "normalized_duplicate_samples": sum(len(v) for v in normalized_dups.values()),
        "exact_groups": exact_dups,
        "normalized_groups": normalized_dups,
    }
```

### 35.3 MinHash للتشابه التقريبي (`dedup/minhash_similarity.py`)

```python
# dedup/minhash_similarity.py
"""
يستخدم MinHash + LSH للعثور بكفاءة على أزواج عينات متشابهة نصيًا
دون مقارنة كل زوج ممكن (O(n^2) غير عملي لآلاف العينات).
يتطلب: pip install datasketch
"""
from datasketch import MinHash, MinHashLSH
import json
from pathlib import Path
import re

def shingle(text: str, k: int = 5) -> set[str]:
    """يقسّم النص إلى k-grams على مستوى الكلمات — أكثر مقاومة
    لإعادة الصياغة الطفيفة من character-level shingling."""
    tokens = re.findall(r"\w+", text.lower())
    return {
        " ".join(tokens[i:i + k]) for i in range(max(1, len(tokens) - k + 1))
    }

def build_minhash(text: str, num_perm: int = 128) -> MinHash:
    m = MinHash(num_perm=num_perm)
    for sh in shingle(text):
        m.update(sh.encode("utf8"))
    return m

def find_near_duplicates(
    samples_jsonl: Path, threshold: float = 0.8, num_perm: int = 128
) -> list[tuple[str, str, float]]:
    lsh = MinHashLSH(threshold=threshold, num_perm=num_perm)
    minhashes: dict[str, MinHash] = {}
    sources: dict[str, str] = {}

    with samples_jsonl.open() as f:
        for line in f:
            sample = json.loads(line)
            sid = sample["sample_id"]
            source = sample["code_context"]["current_method"]
            m = build_minhash(source, num_perm)
            minhashes[sid] = m
            sources[sid] = source
            lsh.insert(sid, m)

    seen_pairs = set()
    near_duplicates = []
    for sid, m in minhashes.items():
        matches = lsh.query(m)
        for match_id in matches:
            if match_id == sid:
                continue
            pair = tuple(sorted([sid, match_id]))
            if pair in seen_pairs:
                continue
            seen_pairs.add(pair)
            similarity = minhashes[sid].jaccard(minhashes[match_id])
            near_duplicates.append((pair[0], pair[1], round(similarity, 3)))

    return sorted(near_duplicates, key=lambda x: -x[2])
```

### 35.4 حسم القرار: أي عينة نُبقي عند وجود تكرار

مجرد اكتشاف التكرار لا يكفي — يجب قرار واضح لأي نسخة تبقى:

```python
# dedup/resolve_duplicates.py
import json
from pathlib import Path

QUALITY_PRIORITY = {"high": 3, "medium": 2, "low": 1}

def choose_canonical(sample_ids: list[str], samples_by_id: dict[str, dict]) -> str:
    """معايير الاختيار بالترتيب:
    1. أعلى quality_score (الفصل 51).
    2. أعلى label_confidence.
    3. الأحدث (created_at) كمعيار فاصل أخير.
    """
    def sort_key(sid):
        s = samples_by_id[sid]
        return (
            s["provenance"]["quality_score"],
            QUALITY_PRIORITY.get(s["provenance"]["label_confidence"], 0),
        )
    return max(sample_ids, key=sort_key)

def resolve_all_duplicates(
    samples_jsonl: Path, duplicate_groups: list[list[str]], output_path: Path
):
    samples_by_id = {}
    with samples_jsonl.open() as f:
        for line in f:
            s = json.loads(line)
            samples_by_id[s["sample_id"]] = s

    to_remove = set()
    kept_canonical = {}
    for group in duplicate_groups:
        canonical = choose_canonical(group, samples_by_id)
        kept_canonical[canonical] = group
        for sid in group:
            if sid != canonical:
                to_remove.add(sid)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w") as fout:
        for sid, sample in samples_by_id.items():
            if sid not in to_remove:
                fout.write(json.dumps(sample, ensure_ascii=False) + "\n")

    print(f"Removed {len(to_remove)} duplicate samples, "
          f"kept {len(samples_by_id) - len(to_remove)}")
    return kept_canonical
```

### 35.5 حالة خاصة: نفس Method عبر إصدارات Android مختلفة

هذه ليست حالة تكرار "خاطئة" دائمًا — method قد تكون متطابقة تمامًا بين android-13 وandroid-14 لأنها فعليًا لم تتغيّر. هنا **لا نحذفها كتكرار عشوائي**، بل نتعامل معها كإشارة خاصة:

```python
def detect_cross_version_stability(
    samples: list[dict]
) -> dict[str, list[str]]:
    """يُرجع مجموعات sample_ids التي تمثل نفس الـmethod عبر إصدارات
    مختلفة — هذه تُعلَّم بحقل إضافي 'cross_version_group' بدل الحذف،
    لأن الاستقرار عبر الإصدارات معلومة مفيدة (تتصل بالفصل 30.2:
    Unchanged secure code) وليست تكرارًا يجب التخلص منه."""
    from collections import defaultdict
    groups = defaultdict(list)
    for s in samples:
        key = (s["source"]["file"], s["source"]["method"])
        groups[key].append(s["sample_id"])
    return {
        f"{k[0]}::{k[1]}": v for k, v in groups.items() if len(v) > 1
    }
```

> **القاعدة الحاسمة لهذا الفصل:** الهدف من Deduplication ليس فقط "تقليل حجم الملف" — بل **منع نفس المحتوى الفعلي من الظهور في كل من Train وTest**. لهذا خطوة Deduplication يجب أن تُنفَّذ **قبل** التقسيم (الفصل 36)، وليس بعده — تشغيلها بعد التقسيم قد يترك نسخة في Train ونسخة في Test دون أن يكتشف السكريبت ذلك لأنه يعمل داخل كل split على حدة.

> **Definition of Done — الجزء الثامن عشر:** تشغيل الـpipeline الكامل (exact → normalized → MinHash) على كل عينات الـDataset الحالية، مع تقرير واضح لعدد المجموعات المكتشفة في كل طبقة، ومراجعة يدوية لخمسة أزواج near-duplicate (من MinHash تحديدًا، threshold ≥ 0.8) للتأكد أنها فعليًا تكرار دلالي وليست false positive نتيجة تشابه سطحي فقط.

---

[← الجزء السابع عشر](./part-17-provenance.md) · [الفهرس](./README.md) · [الجزء التاسع عشر →](./part-19-leakage-prevention.md)
