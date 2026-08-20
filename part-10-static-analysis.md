[← الجزء التاسع](./part-09-parsing.md) · [الفهرس](./README.md)

# الجزء العاشر: Static Analysis Layer

هذا الجزء يحوّل مخرجات الـParser (الجزء التاسع) إلى تمثيل بنيوي غني — **Security Facts** — ثم يستخدم هذا التمثيل لترشيح المواقع التي تستحق مراجعة عميقة من الـLLM. هذه هي الطبقة التي تفصل مشروعنا عن مجرد "إعطاء الملف للنموذج والدعاء".

## الفصل 21: Security Facts Extractor

### 21.1 تصميم التمثيل (Representation)

كل method يمر بهذه الطبقة يُنتِج كائن `SecurityFacts` واحد — تمثيل حتمي، خالٍ من أي reasoning تخميني، يجمع فقط ما هو موجود فعليًا في الكود:

```json
{
  "entry_point": "updateUserSetting",
  "is_binder_entry": true,
  "binder_calls": ["getCallingUid"],
  "permission_checks": [],
  "appops_checks": [],
  "identity_transitions": [
    {"api": "clearCallingIdentity", "line": 42},
    {"api": "restoreCallingIdentity", "line": 47}
  ],
  "user_checks": [],
  "package_uid_checks": [],
  "calls": ["getCallingUid", "clearCallingIdentity", "write", "restoreCallingIdentity"],
  "potential_sinks": ["settingsProvider.write"],
  "caller_controlled_params": ["targetUserId", "key", "value"]
}
```

لاحظ أن هذا التمثيل **لا يحتوي حكمًا أمنيًا** — لا `verdict`, لا `confidence`. هو فقط حقائق. الحكم يأتي لاحقًا من الـLLM بعد بناء الـcontext (الفصل 26).

### 21.2 `static_analysis/security_facts.py`

```python
# static_analysis/security_facts.py
from dataclasses import dataclass, field, asdict
from parser.java_parser import MethodInfo, ClassInfo
from security_rules.catalog_loader import SecurityApiCatalog

# heuristic بسيط لتحديد أن method هي Binder entry point:
# إما أن الكلاس الأب يمتد *.Stub، أو أن الـmethod تحمل @Override
# داخل كلاس يمتد Stub. نعتمد على معلومة الكلاس الممرَّرة من الخارج.

@dataclass
class IdentityTransition:
    api: str
    line: int

@dataclass
class SecurityFacts:
    entry_point: str
    is_binder_entry: bool
    binder_calls: list[str] = field(default_factory=list)
    permission_checks: list[str] = field(default_factory=list)
    appops_checks: list[str] = field(default_factory=list)
    identity_transitions: list[IdentityTransition] = field(default_factory=list)
    user_checks: list[str] = field(default_factory=list)
    package_uid_checks: list[str] = field(default_factory=list)
    calls: list[str] = field(default_factory=list)
    potential_sinks: list[str] = field(default_factory=list)
    caller_controlled_params: list[str] = field(default_factory=list)

SINK_KEYWORDS = [
    "write", "grant", "delete", "remove", "install", "uninstall",
    "setEnabled", "wipe", "reset", "execute", "send",
]

def looks_like_sink(call_name: str) -> bool:
    return any(k.lower() in call_name.lower() for k in SINK_KEYWORDS)

def is_binder_entry_class(cls: ClassInfo) -> bool:
    if not cls.superclass:
        return False
    return "Stub" in cls.superclass or any(
        "Stub" in iface for iface in cls.implemented_interfaces
    )

def infer_caller_controlled_params(method: MethodInfo) -> list[str]:
    """في v0.1: كل معامل من نوع مرجعي (غير primitive بسيط) أو
    من الأنواع الشائعة لهويات (int userId/uid) يُعتبر افتراضيًا
    caller-controlled، تماشيًا مع القاعدة الافتراضية في الفصل 7.3."""
    controlled = []
    identity_like_names = {"userid", "uid", "packagename", "callinguid"}
    for param_type, param_name in method.parameters:
        if param_name.lower() in identity_like_names:
            controlled.append(param_name)
        elif param_type in ("String", "Uri", "Bundle", "Intent"):
            controlled.append(param_name)
    return controlled

def extract_security_facts(
    method: MethodInfo, cls: ClassInfo, catalog: SecurityApiCatalog
) -> SecurityFacts:
    facts = SecurityFacts(
        entry_point=method.name,
        is_binder_entry=is_binder_entry_class(cls),
        calls=list(method.calls),
        caller_controlled_params=infer_caller_controlled_params(method),
    )

    for call in method.calls:
        category = catalog.category_of(call)
        if category == "identity_apis":
            facts.binder_calls.append(call)
            if call in ("clearCallingIdentity", "restoreCallingIdentity"):
                facts.identity_transitions.append(
                    IdentityTransition(api=call, line=method.start_line)
                )
        elif category == "permission_apis":
            facts.permission_checks.append(call)
        elif category == "appops_apis":
            facts.appops_checks.append(call)
        elif category == "cross_user_apis":
            facts.user_checks.append(call)
        elif category == "package_apis":
            facts.package_uid_checks.append(call)

        if looks_like_sink(call):
            facts.potential_sinks.append(call)

    return facts

def facts_to_dict(facts: SecurityFacts) -> dict:
    d = asdict(facts)
    return d
```

### 21.3 تشغيل على ملف كامل

```python
# static_analysis/run_extraction.py
import json
from pathlib import Path
from parser.java_parser import parse_file
from security_rules.catalog_loader import load_catalog
from static_analysis.security_facts import extract_security_facts, facts_to_dict

def extract_file(file_path: Path, catalog) -> list[dict]:
    source = file_path.read_text(errors="replace")
    file_info = parse_file(source)

    results = []
    for cls in file_info.classes:
        for method in cls.methods:
            facts = extract_security_facts(method, cls, catalog)
            results.append({
                "file": str(file_path),
                "class": cls.name,
                **facts_to_dict(facts),
            })
    return results

if __name__ == "__main__":
    catalog = load_catalog()
    target = Path("aosp_sources/android-14/services/core/java/com/android/server/pm")

    all_facts = []
    for java_file in target.glob("*.java"):
        all_facts.extend(extract_file(java_file, catalog))

    out = Path("static_analysis/output/pm_security_facts.jsonl")
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w") as f:
        for record in all_facts:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    print(f"Extracted facts for {len(all_facts)} methods -> {out}")
```

> **Definition of Done — الفصل 21:** تشغيل السكريبت على مجلد حقيقي (مثل `pm/`) ينتج ملف JSONL يحتوي على الأقل عشرات السجلات، مع مراجعة يدوية لخمسة منها للتأكد أن `identity_transitions` و`potential_sinks` تعكس فعليًا محتوى الكود ولا تحتوي أخطاء تصنيف واضحة.

---

## الفصل 22: Candidate Generator

هذا هو المكوّن الذي يحوّل آلاف الـ`SecurityFacts` إلى قائمة قصيرة من **Candidates** — مواقع تستحق فعلًا الوصول لمرحلة الـLLM المكلفة. القاعدة الأساسية: **كل Candidate يُخرِج score، وليس verdict نهائيًا.**

### 22.1 القواعد الأساسية (v0.1)

| القاعدة | الشرط | لماذا هي إشارة قوية |
|---|---|---|
| **Cross-user gap** | Binder entry + معامل `userId`/`targetUserId` caller-controlled + `potential_sinks` غير فارغة + `user_checks` فارغة | انتهاك مباشر لـInvariant #20 (الفصل 9.5) |
| **Package ownership gap** | معامل `packageName` caller-controlled + `potential_sinks` غير فارغة + `package_uid_checks` فارغة | انتهاك محتمل لـInvariant #6 (الفصل 9.2) |
| **Identity transition + late check** | `identity_transitions` غير فارغة + `permission_checks`/`user_checks` غير فارغة، لكن ترتيبها غير مؤكَّد من الـfacts وحدها | مرشّح لـ"Hard Case" يحتاج ترتيب فعلي من الكود — الفصل 26 سيحله بترتيب الأسطر |
| **Sink بدون أي تحقق** | `potential_sinks` غير فارغة + `permission_checks` و`appops_checks` و`user_checks` كلها فارغة | أعلى إشارة أولوية — غياب كامل للتحقق |

### 22.2 `candidate_generator/rules.py`

```python
# candidate_generator/rules.py
from dataclasses import dataclass

@dataclass
class Candidate:
    file: str
    class_name: str
    method_name: str
    rule_name: str
    score: float
    reasons: list[str]

def rule_cross_user_gap(facts: dict) -> Candidate | None:
    if not facts["is_binder_entry"]:
        return None
    caller_params = [p.lower() for p in facts["caller_controlled_params"]]
    has_user_param = any("userid" in p or p == "uid" for p in caller_params)
    if not (has_user_param and facts["potential_sinks"] and not facts["user_checks"]):
        return None

    return Candidate(
        file=facts["file"], class_name=facts["class"], method_name=facts["entry_point"],
        rule_name="cross_user_gap",
        score=8.0,
        reasons=[
            "Binder entry point",
            "caller-controlled user identifier parameter present",
            f"potential sinks: {facts['potential_sinks']}",
            "no cross-user authorization API detected in method body",
        ],
    )

def rule_package_ownership_gap(facts: dict) -> Candidate | None:
    caller_params = [p.lower() for p in facts["caller_controlled_params"]]
    has_package_param = any("packagename" in p for p in caller_params)
    if not (has_package_param and facts["potential_sinks"] and not facts["package_uid_checks"]):
        return None

    return Candidate(
        file=facts["file"], class_name=facts["class"], method_name=facts["entry_point"],
        rule_name="package_ownership_gap",
        score=6.0,
        reasons=[
            "caller-controlled packageName parameter present",
            f"potential sinks: {facts['potential_sinks']}",
            "no package/UID ownership check detected in method body",
        ],
    )

def rule_sink_without_any_check(facts: dict) -> Candidate | None:
    no_checks = (
        not facts["permission_checks"]
        and not facts["appops_checks"]
        and not facts["user_checks"]
    )
    if not (facts["potential_sinks"] and no_checks):
        return None

    return Candidate(
        file=facts["file"], class_name=facts["class"], method_name=facts["entry_point"],
        rule_name="sink_without_any_check",
        score=9.0,
        reasons=[
            f"potential sinks: {facts['potential_sinks']}",
            "no permission, AppOps, or cross-user check detected at all",
        ],
    )

def rule_identity_transition_with_checks(facts: dict) -> Candidate | None:
    has_transition = bool(facts["identity_transitions"])
    has_any_check = bool(facts["permission_checks"] or facts["user_checks"])
    if not (has_transition and has_any_check):
        return None

    return Candidate(
        file=facts["file"], class_name=facts["class"], method_name=facts["entry_point"],
        rule_name="identity_transition_ordering_unclear",
        score=4.0,  # أقل من القواعد الأخرى — يحتاج تحقق ترتيب فعلي، ليس مؤشرًا قاطعًا
        reasons=[
            "identity transition present alongside a security check",
            "ordering between check and clearCallingIdentity must be "
            "verified from source, not assumed",
        ],
    )

ALL_RULES = [
    rule_sink_without_any_check,
    rule_cross_user_gap,
    rule_package_ownership_gap,
    rule_identity_transition_with_checks,
]

def generate_candidates(facts: dict) -> list[Candidate]:
    candidates = []
    for rule in ALL_RULES:
        result = rule(facts)
        if result:
            candidates.append(result)
    return candidates
```

### 22.3 تجميع النتائج

```python
# candidate_generator/run_generation.py
import json
from pathlib import Path
from dataclasses import asdict
from candidate_generator.rules import generate_candidates

def process(facts_jsonl: Path, output_path: Path, min_score: float = 4.0):
    output_path.parent.mkdir(parents=True, exist_ok=True)
    total_methods = 0
    total_candidates = 0

    with facts_jsonl.open() as fin, output_path.open("w") as fout:
        for line in fin:
            facts = json.loads(line)
            total_methods += 1
            for candidate in generate_candidates(facts):
                if candidate.score >= min_score:
                    fout.write(json.dumps(asdict(candidate), ensure_ascii=False) + "\n")
                    total_candidates += 1

    print(f"{total_candidates} candidates generated from {total_methods} methods "
          f"(min_score={min_score})")

if __name__ == "__main__":
    process(
        facts_jsonl=Path("static_analysis/output/pm_security_facts.jsonl"),
        output_path=Path("candidate_generator/output/pm_candidates.jsonl"),
    )
```

> **قاعدة تصميمية مهمة:** لاحظ أن `rule_identity_transition_with_checks` تُعطي score أقل من القواعد الأخرى عمدًا — لأنها لا تكتشف غيابًا واضحًا لشيء، بل حالة **يحتاج التحقق منها فعليًا بترتيب الأسطر** (وهذا بالضبط مثال Vulnerable/Secure المتطابقين شكليًا من الفصل 5.4). هذا Candidate تحديدًا لن يُحسَم إلا بواسطة الـLLM بعد رؤية الكود الفعلي بترتيبه الصحيح.

> **Definition of Done — الجزء العاشر:** قائمة Candidates ناتجة فعليًا من ملفات `pm/` الحقيقية، مع مراجعة يدوية لعشرة Candidates على الأقل للتأكد أن الأسباب المذكورة (`reasons`) تعكس الكود الفعلي، وأن نسبة الـFalse Positives الظاهرة عند القراءة اليدوية معقولة (لن تكون صفرًا في v0.1 — هذا متوقَّع، القواعد هنا Recall-first بتصميم).

---

[← الجزء التاسع](./part-09-parsing.md) · [الفهرس](./README.md) · [الجزء الحادي عشر →](./part-11-call-graph.md)
