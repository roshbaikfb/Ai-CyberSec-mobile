[← الجزء الرابع عشر](./part-14-vulnerable-fixed-pairs.md) · [الفهرس](./README.md)

# الجزء الخامس عشر: Secure Negatives

كما وضحنا في الفصل 2 والفصل 27، نموذج يقول "كل شيء vulnerable" يحقق Recall مثاليًا وقيمة عملية معدومة. هذا الجزء يبني الطبقة التي تمنع هذا الانحراف — بنفس الجدية والاستثمار الذي بُذل في العينات الإيجابية.

## الفصل 30: Negative Samples

### 30.1 أربعة مصادر للـNegatives

| المصدر | كيف نحصل عليه | الجودة النسبية |
|---|---|---|
| **Unchanged secure code** | methods لم تتغيّر إطلاقًا عبر عدة إصدارات Android، وتحتوي تحقق أمني واضح | عالية — استقرار عبر الزمن مؤشر جيد على الصحة، لكن ليس دليلًا قاطعًا |
| **Fixed code (بعد patch)** | نفس مخرجات `task_8_fixed_version_secure` من الفصل 29 | عالية جدًا — لدينا سياق before/after كامل يفسّر لماذا هي آمنة الآن |
| **Code reviews موثَّقة** | تعليقات مراجعة كود عامة (إن وُجدت في PR history) تؤكد صراحة أن نمطًا معينًا آمن | متوسطة — تعتمد على توفر توثيق فعلي، نادر في AOSP تحديدًا |
| **أنماط مُتحقَّق منها يدويًا** | باحث بشري يراجع كودًا ويكتب تحليلًا كاملاً بنفسه (الأبطأ لكن الأدق) | الأعلى جودة — أساس Benchmark (الفصل 38) |

### 30.2 `negative_mining/unchanged_stable_code.py`

هذا المصدر يبحث عن methods تحمل بصمة (hash) متطابقة تمامًا عبر عدة إصدارات Android متتالية — استقرار طويل الأمد كإشارة أولية (وليست حاسمة) على عدم وجود مشاكل معروفة فيها.

```python
# negative_mining/unchanged_stable_code.py
import hashlib
import json
from pathlib import Path
from dataclasses import dataclass, asdict
from parser.java_parser import parse_file

@dataclass
class StableMethodCandidate:
    class_name: str
    method_name: str
    file_path: str
    source_code: str
    versions_seen: list[str]
    normalized_hash: str

def normalize_source(source: str) -> str:
    """يزيل whitespace وcomments لضمان أن التطابق يعتمد على المنطق
    الفعلي وليس تنسيقًا سطحيًا. تبسيط v0.1 — لا يتعامل مع كل حالات
    التعليقات المعقدة، لكن يكفي كخطوة أولى."""
    import re
    no_comments = re.sub(r"//.*", "", source)
    no_comments = re.sub(r"/\*.*?\*/", "", no_comments, flags=re.DOTALL)
    return re.sub(r"\s+", " ", no_comments).strip()

def hash_method(source: str) -> str:
    normalized = normalize_source(source)
    return hashlib.sha256(normalized.encode("utf8")).hexdigest()

def find_stable_methods(
    version_dirs: dict[str, Path], target_subpath: str
) -> list[StableMethodCandidate]:
    """version_dirs: {'android-12': Path(...), 'android-13': Path(...), ...}"""
    method_hashes: dict[str, dict] = {}  # key = f"{class}.{method}" -> {hash, versions, source, ...}

    for version_label, root in version_dirs.items():
        target = root / target_subpath
        if not target.exists():
            continue
        for java_file in target.glob("*.java"):
            try:
                source = java_file.read_text(errors="replace")
                file_info = parse_file(source)
            except Exception:
                continue
            for cls in file_info.classes:
                for method in cls.methods:
                    key = f"{cls.name}.{method.name}"
                    h = hash_method(method.body_source)
                    if key not in method_hashes:
                        method_hashes[key] = {
                            "class_name": cls.name, "method_name": method.name,
                            "file_path": str(java_file), "source_code": method.body_source,
                            "hash": h, "versions": [version_label],
                        }
                    elif method_hashes[key]["hash"] == h:
                        method_hashes[key]["versions"].append(version_label)
                    # لو الهاش اختلف: الـmethod تغيّرت — لن تُعتبر stable

    stable = [
        StableMethodCandidate(
            class_name=v["class_name"], method_name=v["method_name"],
            file_path=v["file_path"], source_code=v["source_code"],
            versions_seen=v["versions"], normalized_hash=v["hash"],
        )
        for v in method_hashes.values()
        if len(v["versions"]) >= 3  # استقرار عبر 3 إصدارات على الأقل
    ]
    return stable

if __name__ == "__main__":
    version_dirs = {
        "android-12": Path("aosp_sources/android-12"),
        "android-13": Path("aosp_sources/android-13"),
        "android-14": Path("aosp_sources/android-14"),
    }
    stable = find_stable_methods(
        version_dirs, "services/core/java/com/android/server/pm"
    )
    out = Path("negative_mining/output/stable_candidates.jsonl")
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w") as f:
        for c in stable:
            f.write(json.dumps(asdict(c), ensure_ascii=False) + "\n")
    print(f"Found {len(stable)} methods stable across 3+ versions")
```

> **تحذير مهم:** استقرار method عبر عدة إصدارات **لا يعني أنها آمنة بالضرورة** — قد تكون ثغرة لم تُكتشف بعد. لهذا كل `StableMethodCandidate` يمر إلزاميًا عبر مراجعة (يدوية أو موثَّقة) قبل أن يُصبح `negative sample` رسمي في الـDataset — لا نصنّفها `secure` تلقائيًا بناءً على الاستقرار وحده.

### 30.3 معايير القبول لـNegative Sample

قبل أن يدخل أي negative candidate للـDataset الرسمي، يجب أن يحقق:

1. **وجود تحقق أمني واضح وكافٍ** في الكود نفسه (وليس غيابه فقط — غياب أي مؤشر خطر ≠ أمان مؤكَّد).
2. **تفسير صريح** لماذا هذا التحقق كافٍ (يُكتب يدويًا أو عبر Teacher Model + تحقق — الفصل 50).
3. **`counter_evidence` فارغة أو ضعيفة** — لو وُجد سبب معقول للشك، الحالة تُصنَّف `ambiguous` بدل `secure` قسرًا.

---

## الفصل 31: Hard Negative Mining

هذا هو الفصل الأهم في الجزء الخامس عشر، وأحد أهم فصول الكتاب بالكامل. كما أوضحنا في الفصل 5، أقوى Negative Samples ليست الأكواد الواضحة الأمان — بل الأكواد التي **تشبه ثغرة حقيقية شكليًا لكنها آمنة فعليًا**.

### 31.1 الأنماط الخمسة المستهدفة تحديدًا

هذه القائمة مطابقة تمامًا لما حُدِّد في متطلبات المشروع الأصلية — وهي الأولوية القصوى لتقليل False Positives:

1. `clearCallingIdentity()` الآمن (تحقق حدث قبله).
2. `userId` caller-controlled **مع** cross-user check موجود وصحيح الترتيب.
3. `packageName` **مع** UID validation موجود.
4. عمليات مميزة تحدث **بعد** authorization صحيح ومكتمل.
5. أنماط AppOps تبدو خطرة شكليًا لكنها صحيحة فعليًا (مثل استخدام `checkOpNoThrow` بدل الاستثناء — قد يبدو "أضعف" لكنه مناسب في سياقات لا تتطلب رمي استثناء).

### 31.2 استراتيجية التوليد: Candidates أولًا، ثم مراجعة

```python
# negative_mining/hard_negative_pipeline.py
"""
Pipeline من مرحلتين:
  المرحلة 1: البحث عن methods تحتوي pattern مشبوه شكليًا (نفس قواعد
             candidate_generator من الفصل 22) لكن مع security check
             ظاهر **قبل** الـpattern المشبوه في نفس method.
  المرحلة 2: كل candidate من هذه القائمة يمر لمراجعة (بشرية أو
             Teacher Model + تحقق) قبل اعتماده كـhard negative نهائي.
هذا الـpipeline لا "يقرر" أن شيئًا آمن تلقائيًا — فقط يرشّح.
"""
import json
import re
from pathlib import Path
from dataclasses import dataclass, asdict

@dataclass
class HardNegativeCandidate:
    file: str
    class_name: str
    method_name: str
    pattern_type: str
    source_code: str
    check_line_estimate: int | None
    identity_change_line_estimate: int | None
    ordering_looks_correct: bool  # True لو التحقق يسبق التغيير نصيًا —
                                    # لا يزال يحتاج تأكيد بشري

def find_line_of_first_match(source: str, patterns: list[str]) -> int | None:
    lines = source.splitlines()
    for i, line in enumerate(lines):
        if any(p in line for p in patterns):
            return i + 1
    return None

def check_clear_identity_pattern(
    file_path: str, class_name: str, method_name: str, source: str
) -> HardNegativeCandidate | None:
    if "clearCallingIdentity" not in source:
        return None

    check_patterns = [
        "enforceCallingPermission", "checkCallingPermission",
        "enforceCrossUserPermission", "checkPackage",
    ]
    check_line = find_line_of_first_match(source, check_patterns)
    identity_line = find_line_of_first_match(source, ["clearCallingIdentity"])

    if not check_line:
        return None  # لا يوجد تحقق ظاهر أصلاً — هذا مرشّح Vulnerable وليس Negative

    return HardNegativeCandidate(
        file=file_path, class_name=class_name, method_name=method_name,
        pattern_type="safe_clear_identity",
        source_code=source,
        check_line_estimate=check_line,
        identity_change_line_estimate=identity_line,
        ordering_looks_correct=(check_line < (identity_line or float("inf"))),
    )

def check_cross_user_pattern(
    file_path: str, class_name: str, method_name: str, source: str,
    caller_controlled_params: list[str]
) -> HardNegativeCandidate | None:
    has_user_param = any(
        "userid" in p.lower() or p.lower() == "uid" for p in caller_controlled_params
    )
    if not has_user_param:
        return None

    cross_user_patterns = ["enforceCrossUserPermission", "handleIncomingUser"]
    check_line = find_line_of_first_match(source, cross_user_patterns)
    if not check_line:
        return None

    identity_line = find_line_of_first_match(source, ["clearCallingIdentity"])

    return HardNegativeCandidate(
        file=file_path, class_name=class_name, method_name=method_name,
        pattern_type="safe_cross_user_check",
        source_code=source,
        check_line_estimate=check_line,
        identity_change_line_estimate=identity_line,
        ordering_looks_correct=(
            identity_line is None or check_line < identity_line
        ),
    )

def check_package_ownership_pattern(
    file_path: str, class_name: str, method_name: str, source: str,
    caller_controlled_params: list[str]
) -> HardNegativeCandidate | None:
    has_package_param = any(
        "packagename" in p.lower() for p in caller_controlled_params
    )
    if not has_package_param:
        return None

    ownership_patterns = ["checkPackage", "getPackageUid", "verifyPackage"]
    check_line = find_line_of_first_match(source, ownership_patterns)
    if not check_line:
        return None

    return HardNegativeCandidate(
        file=file_path, class_name=class_name, method_name=method_name,
        pattern_type="safe_package_ownership",
        source_code=source,
        check_line_estimate=check_line,
        identity_change_line_estimate=None,
        ordering_looks_correct=True,  # لا يوجد identity change ذو صلة هنا
    )

ALL_HARD_NEGATIVE_CHECKS = [
    check_clear_identity_pattern,
    check_cross_user_pattern,
    check_package_ownership_pattern,
]

def mine_hard_negatives(facts_jsonl: Path, output_path: Path):
    output_path.parent.mkdir(parents=True, exist_ok=True)
    total, found = 0, 0

    with facts_jsonl.open() as fin, output_path.open("w") as fout:
        for line in fin:
            facts = json.loads(line)
            total += 1
            # نحتاج source_code الكامل — بفرض أنه محفوظ ضمن facts
            # (يُضاف كحقل إضافي عند تشغيل الفصل 21 لهذا الغرض تحديدًا)
            source = facts.get("full_method_source", "")
            if not source:
                continue

            for check_fn in ALL_HARD_NEGATIVE_CHECKS:
                if check_fn.__name__ == "check_clear_identity_pattern":
                    result = check_fn(facts["file"], facts["class"],
                                       facts["entry_point"], source)
                else:
                    result = check_fn(facts["file"], facts["class"],
                                       facts["entry_point"], source,
                                       facts["caller_controlled_params"])
                if result:
                    fout.write(json.dumps(asdict(result), ensure_ascii=False) + "\n")
                    found += 1

    print(f"{found} hard negative candidates found from {total} methods "
          f"(all require manual/reviewed confirmation before dataset inclusion)")
```

### 31.3 مثال Hard Negative فعلي بعد المراجعة

بعد المراجعة اليدوية للـCandidate، يتحوّل لـSample رسمي بصيغة الفصل 27:

```json
{
  "sample_id": "aosp_hardneg_00042",
  "source": {
    "project": "frameworks/base",
    "android_version": "14",
    "commit_before": null,
    "commit_after": null,
    "file": "services/core/java/com/android/server/pm/PackageManagerService.java",
    "method": "clearApplicationUserData",
    "cve": null
  },
  "task": "android_framework_security_review",
  "code_context": {
    "current_method": "... (full source) ...",
    "caller": null,
    "security_helpers": {},
    "sink": null,
    "annotations": null,
    "unresolved_notes": []
  },
  "analysis": {
    "entry_point": "clearApplicationUserData",
    "caller": "unknown_external_caller",
    "caller_identity": "untrusted_application_uid",
    "attacker_controlled_inputs": ["packageName", "userId"],
    "permission_checks": ["enforceCallingPermission"],
    "appops_checks": [],
    "identity_transitions": ["clearCallingIdentity", "restoreCallingIdentity"],
    "cross_user_checks": ["enforceCrossUserPermission"],
    "privileged_operations": ["clearApplicationUserDataInternal"],
    "trust_boundary": "application_to_system_server",
    "security_invariant": "A caller must not perform an operation on behalf of another Android user without an explicit, verifiable cross-user authorization check performed before the caller's original identity is lost.",
    "candidate_issue": "None — cross-user authorization is verified before identity transition.",
    "counter_evidence": [
      "enforceCrossUserPermission is called with the original caller UID before clearCallingIdentity",
      "the privileged operation itself does not re-read caller identity after the transition"
    ],
    "missing_context": [],
    "confidence": 0.9
  },
  "verdict": "secure",
  "provenance": {
    "generation_method": "hard_negative_mined",
    "reviewer": "manual_v1",
    "label_confidence": "high",
    "quality_score": 28
  }
}
```

لاحظ أن `counter_evidence` هنا ليست فارغة — بل تحتوي **الأدلة التي تدعم الحكم الآمن** صراحة. هذا مقصود: في عينات negative، حقل `counter_evidence` يُستخدم لتوثيق أدلة الأمان بنفس الصرامة التي نوثّق بها أدلة الثغرة في عينات positive.

> **Definition of Done — الجزء الخامس عشر:** لا أقل من 30 Hard Negative candidate مُستخرَجة عبر الـpipeline، مع مراجعة يدوية لكل واحدة (100% — هذا الجزء لا يُقبَل فيه تلقائي بدون مراجعة بشرية في v0.1 نظرًا لحساسيته)، ونسبة قبول موثَّقة (كم candidate تحوّل فعليًا لـsample نهائي مقابل كم رُفِض لأن الترتيب أو التحقق لم يكن كافيًا فعليًا عند الفحص الدقيق).

---

[← الجزء الرابع عشر](./part-14-vulnerable-fixed-pairs.md) · [الفهرس](./README.md) · [الجزء السادس عشر →](./part-16-insufficient-context.md)
