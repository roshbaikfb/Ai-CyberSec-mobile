[← الجزء الثالث عشر](./part-13-dataset-design.md) · [الفهرس](./README.md)

# الجزء الرابع عشر: Vulnerable/Fixed Pairs

## الفصل 29: تحويل Patch إلى Samples

هذا الفصل هو أكثر مكوّن في المشروع كفاءة من حيث نسبة القيمة إلى الجهد: **patch واحد حقيقي (من الجزء السابع) يمكن أن يُنتِج تسع Samples مختلفة على الأقل**، كل واحدة تدرّب النموذج على جانب مختلف من نفس الحالة.

### 29.1 لماذا لا نكتفي بـSample واحد لكل Patch

Sample واحدة بصيغة "هذا الكود قبل التعديل vulnerable، وبعده secure" تُعلّم النموذج **حفظ** هذا التمييز تحديدًا. لكن الهدف — كما حُدِّد في الفصل 1 — هو تعليم **منهجية**. تفكيك نفس الـPatch لعدة أسئلة مختلفة يجبر النموذج على التعامل مع كل جانب من جوانب التحليل (Sources، Trust Boundary، Invariant، إلخ) كمهارة مستقلة قابلة للتعميم على patches لم يرها إطلاقًا.

### 29.2 التسعة أنواع من المهام (Tasks)

| # | المهمة | يختبر ماذا |
|---|---|---|
| 1 | Is old version vulnerable? | القدرة الأساسية على إصدار حكم `vulnerable` بالنسخة القديمة |
| 2 | What invariant was added? | ربط الإصلاح بمكتبة الفصل 9 — فهم المبدأ لا الحفظ |
| 3 | Locate missing authorization | Localization Accuracy (الفصل 2) — تحديد الموضع الدقيق |
| 4 | Compare before/after | القدرة على تفسير الفرق كسبب أمني، لا كتغيير نصي عشوائي |
| 5 | Determine caller-controlled input | تصنيف Source بدقة (الفصل 8) |
| 6 | Identify trust boundary | تطبيق مفهوم الفصل 7 على حالة فعلية |
| 7 | Explain why patch fixes issue | Root Cause Accuracy (الفصل 2) — ليس فقط "أين" بل "لماذا" |
| 8 | Is fixed version secure? | القدرة على إصدار حكم `secure` — بنفس الأهمية بالضبط لتفادي التحيّز نحو "كل شيء vulnerable" |
| 9 | What context is still missing? | تدريب على الاعتراف بعدم اليقين حتى في حالة مألوفة نسبيًا |

### 29.3 `sample_generator/patch_to_samples.py`

```python
# sample_generator/patch_to_samples.py
"""
يستهلك زوج before/after (من الفصل 17) بعد إثرائه بـSecurity Facts
(الفصل 21) والـcontext المُجمَّع (الفصل 26)، وينتج قائمة DatasetSample
متوافقة مع الـSchema (الفصل 27).

ملاحظة مهمة: هذا السكريبت ينتج "مسودات" (drafts) للحقول النصية
(security_invariant, candidate_issue, ...) والتي تحتاج إما:
  (أ) صياغة يدوية من باحث بشري، أو
  (ب) توليد بمساعدة نموذج أقوى ثم تحقق (الفصل 50 — Teacher Model Workflow).
هذا السكريبت لا يُنتج نصوصًا نهائية عشوائيًا بلا مصدر — كل حقل نصي
يُبنى من معطيات حتمية (Security Facts، Invariant المطابق) وليس تخمينًا حرًا.
"""
from dataclasses import dataclass
import uuid

@dataclass
class PatchDrivenInputs:
    commit_before: str
    commit_after: str
    file_path: str
    android_version: str
    method_name: str
    before_source: str
    after_source: str
    before_facts: dict   # مخرجات الفصل 21 على النسخة القديمة
    after_facts: dict    # مخرجات الفصل 21 على النسخة الجديدة
    matched_invariant_id: int | None  # رقم من مكتبة الفصل 9، يُحدَّد يدويًا
                                       # أو عبر مطابقة نصية للـdiff (v0.1: يدوي)
    matched_invariant_text: str | None

def _base_source_dict(inputs: PatchDrivenInputs, version: str) -> dict:
    return {
        "project": "frameworks/base",
        "android_version": inputs.android_version,
        "commit_before": inputs.commit_before,
        "commit_after": inputs.commit_after,
        "file": inputs.file_path,
        "method": inputs.method_name,
        "cve": None,
    }

def _new_sample_id() -> str:
    return f"aosp_{uuid.uuid4().hex[:12]}"

def task_1_old_version_vulnerable(inputs: PatchDrivenInputs) -> dict:
    facts = inputs.before_facts
    missing_checks = (
        not facts["permission_checks"]
        and not facts["user_checks"]
        and not facts["appops_checks"]
    )
    return {
        "sample_id": _new_sample_id(),
        "source": _base_source_dict(inputs, "before"),
        "task": "android_framework_security_review",
        "code_context": {
            "current_method": inputs.before_source,
            "caller": None, "security_helpers": {}, "sink": None,
            "annotations": None, "unresolved_notes": [],
        },
        "analysis": {
            "entry_point": inputs.method_name,
            "caller": "unknown_external_caller",
            "caller_identity": "untrusted_application_uid",
            "attacker_controlled_inputs": facts["caller_controlled_params"],
            "permission_checks": facts["permission_checks"],
            "appops_checks": facts["appops_checks"],
            "identity_transitions": [t["api"] for t in facts["identity_transitions"]],
            "cross_user_checks": facts["user_checks"],
            "privileged_operations": facts["potential_sinks"],
            "trust_boundary": "application_to_system_server",
            "security_invariant": inputs.matched_invariant_text or "",
            "candidate_issue": (
                "Missing authorization check prior to privileged operation."
                if missing_checks else
                "Partial or ordering-dependent authorization issue — see patch diff."
            ),
            "counter_evidence": [],
            "missing_context": [],
            "confidence": 0.75 if missing_checks else 0.55,
        },
        "verdict": "vulnerable",
        "provenance": {
            "generation_method": "patch_derived",
            "reviewer": "auto_draft_v1",
            "label_confidence": "medium",
            "quality_score": 0,  # يُملأ لاحقًا في الفصل 51
        },
    }

def task_8_fixed_version_secure(inputs: PatchDrivenInputs) -> dict:
    facts = inputs.after_facts
    has_checks = bool(
        facts["permission_checks"] or facts["user_checks"] or facts["appops_checks"]
    )
    return {
        "sample_id": _new_sample_id(),
        "source": _base_source_dict(inputs, "after"),
        "task": "android_framework_security_review",
        "code_context": {
            "current_method": inputs.after_source,
            "caller": None, "security_helpers": {}, "sink": None,
            "annotations": None, "unresolved_notes": [],
        },
        "analysis": {
            "entry_point": inputs.method_name,
            "caller": "unknown_external_caller",
            "caller_identity": "untrusted_application_uid",
            "attacker_controlled_inputs": facts["caller_controlled_params"],
            "permission_checks": facts["permission_checks"],
            "appops_checks": facts["appops_checks"],
            "identity_transitions": [t["api"] for t in facts["identity_transitions"]],
            "cross_user_checks": facts["user_checks"],
            "privileged_operations": facts["potential_sinks"],
            "trust_boundary": "application_to_system_server",
            "security_invariant": inputs.matched_invariant_text or "",
            "candidate_issue": "No demonstrated authorization bypass after fix.",
            "counter_evidence": [
                f"Authorization check(s) present: {facts['user_checks'] + facts['permission_checks']}"
            ] if has_checks else [],
            "missing_context": [],
            "confidence": 0.8 if has_checks else 0.5,
        },
        "verdict": "secure",
        "provenance": {
            "generation_method": "patch_derived",
            "reviewer": "auto_draft_v1",
            "label_confidence": "medium",
            "quality_score": 0,
        },
    }

def task_2_what_invariant_was_added(inputs: PatchDrivenInputs) -> dict | None:
    if not inputs.matched_invariant_text:
        return None  # لا نولّد هذه المهمة بدون invariant مطابَق فعليًا — لا نخترع واحدًا
    sample = task_8_fixed_version_secure(inputs)
    sample["sample_id"] = _new_sample_id()
    sample["task"] = "android_framework_security_review"
    sample["analysis"]["candidate_issue"] = (
        f"The patch added the following invariant enforcement: "
        f"{inputs.matched_invariant_text}"
    )
    return sample

def task_5_determine_caller_controlled_input(inputs: PatchDrivenInputs) -> dict:
    sample = task_1_old_version_vulnerable(inputs)
    sample["sample_id"] = _new_sample_id()
    sample["analysis"]["candidate_issue"] = (
        f"Caller-controlled inputs identified: "
        f"{inputs.before_facts['caller_controlled_params']}"
    )
    return sample

def task_6_identify_trust_boundary(inputs: PatchDrivenInputs) -> dict:
    sample = task_1_old_version_vulnerable(inputs)
    sample["sample_id"] = _new_sample_id()
    sample["analysis"]["candidate_issue"] = (
        "Trust boundary: application (untrusted) -> system_server "
        "(privileged) via Binder IPC."
    )
    return sample

def task_9_insufficient_context_variant(inputs: PatchDrivenInputs) -> dict:
    """نسخة معدَّلة من before تُخفي التحقق الموجود فعليًا في الكود المحيط
    (لو وُجد) لبناء حالة insufficient_context — يُستخدم لاحقًا بشكل مكثف
    في الفصل 32، هنا فقط مثال توضيحي مبسّط."""
    sample = task_1_old_version_vulnerable(inputs)
    sample["sample_id"] = _new_sample_id()
    sample["code_context"]["unresolved_notes"] = [
        "Caller of this method not available in current context.",
    ]
    sample["analysis"]["candidate_issue"] = (
        "Cannot determine caller's prior validation state without "
        "visibility into the calling method."
    )
    sample["analysis"]["missing_context"] = ["caller method definition"]
    sample["analysis"]["confidence"] = 0.3
    sample["verdict"] = "insufficient_context"
    return sample

def generate_all_samples(inputs: PatchDrivenInputs) -> list[dict]:
    """يُنتج كل المهام الممكنة لهذا الـpatch. بعض المهام (مثل #2)
    تُترَك خارج القائمة لو المعطيات اللازمة غير متوفرة — لا نخترع
    محتوى بدل ذلك."""
    samples = [
        task_1_old_version_vulnerable(inputs),
        task_8_fixed_version_secure(inputs),
        task_5_determine_caller_controlled_input(inputs),
        task_6_identify_trust_boundary(inputs),
        task_9_insufficient_context_variant(inputs),
    ]
    invariant_sample = task_2_what_invariant_was_added(inputs)
    if invariant_sample:
        samples.append(invariant_sample)
    return samples
```

### 29.4 تشغيل على دفعة من الـPairs

```python
# sample_generator/run_generation.py
import json
from pathlib import Path
from sample_generator.patch_to_samples import PatchDrivenInputs, generate_all_samples
from static_analysis.security_facts import extract_security_facts
from parser.java_parser import parse_file
from security_rules.catalog_loader import load_catalog

def build_inputs_from_pair(pair: dict, catalog) -> PatchDrivenInputs | None:
    before_info = parse_file(pair["before"]["source_code"]) if pair.get("before") else None
    after_info = parse_file(pair["after"]["source_code"]) if pair.get("after") else None
    if not before_info or not after_info:
        return None
    if not before_info.classes or not after_info.classes:
        return None

    before_method = before_info.classes[0].methods[0] if before_info.classes[0].methods else None
    after_method = after_info.classes[0].methods[0] if after_info.classes[0].methods else None
    if not before_method or not after_method:
        return None

    before_facts = extract_security_facts(before_method, before_info.classes[0], catalog)
    after_facts = extract_security_facts(after_method, after_info.classes[0], catalog)

    from dataclasses import asdict
    return PatchDrivenInputs(
        commit_before=pair["parent_hash"],
        commit_after=pair["commit_hash"],
        file_path=pair["file_path"],
        android_version="14",
        method_name=pair["before"]["method_signature"],
        before_source=pair["before"]["source_code"],
        after_source=pair["after"]["source_code"],
        before_facts=asdict(before_facts),
        after_facts=asdict(after_facts),
        matched_invariant_id=None,       # يُملأ يدويًا في مرحلة المراجعة
        matched_invariant_text=None,
    )

def process(pairs_jsonl: Path, output_path: Path):
    catalog = load_catalog()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    total_pairs, total_samples = 0, 0

    with pairs_jsonl.open() as fin, output_path.open("w") as fout:
        for line in fin:
            pair = json.loads(line)
            total_pairs += 1
            inputs = build_inputs_from_pair(pair, catalog)
            if not inputs:
                continue
            for sample in generate_all_samples(inputs):
                fout.write(json.dumps(sample, ensure_ascii=False) + "\n")
                total_samples += 1

    print(f"{total_samples} draft samples generated from {total_pairs} patch pairs "
          f"(avg {total_samples/max(1,total_pairs):.1f} samples/patch)")

if __name__ == "__main__":
    process(
        pairs_jsonl=Path("patch_miner/output/android-14_before_after.jsonl"),
        output_path=Path("sample_generator/output/android-14_draft_samples.jsonl"),
    )
```

> **تنبيه أساسي:** هذه العينات **مسوّدات** (`generation_method: auto_draft_v1`، `quality_score: 0`). لا تدخل مرحلة التدريب مباشرة — يجب أن تمر عبر مراجعة (الفصل 51: Quality Scoring) قبل الاعتماد. كثير من الحقول النصية (`candidate_issue`, `security_invariant`) هنا مبسَّطة جدًا وتحتاج صياغة أدق من مراجع بشري أو Teacher Model موثَّق (الفصل 50).

> **Definition of Done — الجزء الرابع عشر:** تشغيل السكريبت على الأقل على 20 patch pair حقيقية من مخرجات الفصل 17، ينتج ما لا يقل عن 80 sample مسودة (متوسط 4+ لكل patch)، مع مراجعة يدوية لخمس عينات كاملة للتأكد أن الحقول الأساسية (`attacker_controlled_inputs`, `trust_boundary`) منطقية وليست فارغة أو خاطئة بشكل واضح.

---

[← الجزء الثالث عشر](./part-13-dataset-design.md) · [الفهرس](./README.md) · [الجزء الخامس عشر →](./part-15-secure-negatives.md)
