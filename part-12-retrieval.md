[← الجزء الحادي عشر](./part-11-call-graph.md) · [الفهرس](./README.md)

# الجزء الثاني عشر: Retrieval

الفصل السابق حدد **ماذا نحتاج** (`unresolved_security_calls`, `direct_callees`...). هذا الجزء يبني الأداة التي **تجلب فعليًا** تعريفات هذه العناصر من المستودع، ثم تجمّعها ضمن ميزانية Token محددة.

## الفصل 25: Code Retriever

### 25.1 لماذا لا نبدأ بـVector DB

| النهج | متى يفيد | لماذا نؤجله هنا |
|---|---|---|
| Lexical/Symbol search | البحث عن اسم method/class محدد بدقة | هذا بالضبط احتياجنا الأساسي — استرجاع تعريف `enforceCrossUserPermission` باسمه، وليس بحثًا دلاليًا غامضًا |
| Symbol index (بناء فهرس اسم → موقع) | سريع جدًا، بسيط، لا يحتاج نموذج embedding إضافي | لا عيب حقيقي لحالتنا |
| Embeddings / Vector DB | مفيد لأسئلة دلالية مثل "أين تحدث عمليات تشبه هذه في المفهوم" | تعقيد إضافي (نموذج embedding، فهرسة متجهية، تحديثات) غير مبرَّر عندما يكون الاستعلام الفعلي هو اسم دالة معروف بدقة |

**القرار:** نبني Symbol Index كخطوة أولى وأساسية. نضيف Embeddings لاحقًا فقط إن أثبتت التجارب حاجة فعلية (مثلًا: البحث عن "طرق تحقق مشابهة مفهوميًا" عبر ملفات مختلفة الأسماء) — وهذا قرار نُرجئه لما بعد Milestone 4 (سيُذكر لاحقًا).

### 25.2 بناء Symbol Index

```python
# retriever/symbol_index.py
"""
فهرس بسيط: (class_name, method_name) -> {file_path, source_code, start_line, end_line}
يُبنى مرة واحدة لكل نسخة AOSP، ويُحفَظ كـJSON لإعادة الاستخدام السريع
دون إعادة تحليل كل الملفات في كل مرة.
"""
import json
from pathlib import Path
from dataclasses import dataclass, asdict
from parser.java_parser import parse_file

@dataclass
class SymbolEntry:
    class_name: str
    method_name: str
    file_path: str
    start_line: int
    end_line: int
    source_code: str
    parameters: list[tuple[str, str]]

def build_symbol_index(root_dir: Path) -> dict[str, list[dict]]:
    """المفتاح هو method_name وحده (بدون الكلاس) — لأن الاستعلام
    الشائع (من الفصل 24) هو 'أين تعريف checkCaller؟' دون معرفة الكلاس
    مسبقًا. القيمة قائمة لأن أكثر من كلاس قد يملك method بنفس الاسم."""
    index: dict[str, list[dict]] = {}

    for java_file in root_dir.rglob("*.java"):
        try:
            source = java_file.read_text(errors="replace")
            file_info = parse_file(source)
        except Exception:
            continue

        for cls in file_info.classes:
            for method in cls.methods:
                entry = SymbolEntry(
                    class_name=cls.name,
                    method_name=method.name,
                    file_path=str(java_file),
                    start_line=method.start_line,
                    end_line=method.end_line,
                    source_code=method.body_source,
                    parameters=method.parameters,
                )
                index.setdefault(method.name, []).append(asdict(entry))

    return index

def save_index(index: dict, output_path: Path):
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(index, ensure_ascii=False))

def load_index(path: Path) -> dict:
    return json.loads(path.read_text())

if __name__ == "__main__":
    idx = build_symbol_index(
        Path("aosp_sources/android-14/services/core/java/com/android/server")
    )
    save_index(idx, Path("retriever/output/android-14_symbol_index.json"))
    print(f"Indexed {len(idx)} unique method names")
```

### 25.3 واجهة الاسترجاع (`retriever/code_retriever.py`)

```python
# retriever/code_retriever.py
from dataclasses import dataclass

@dataclass
class RetrievalResult:
    query: str
    found: bool
    candidates: list[dict]  # قد يكون أكثر من واحد — نترك القرار للـContext Builder
    ambiguous: bool          # True لو أكثر من تعريف بنفس الاسم في كلاسات مختلفة

class CodeRetriever:
    def __init__(self, symbol_index: dict[str, list[dict]]):
        self.symbol_index = symbol_index

    def find_method(self, method_name: str,
                     preferred_class: str | None = None) -> RetrievalResult:
        matches = self.symbol_index.get(method_name, [])
        if not matches:
            return RetrievalResult(query=method_name, found=False,
                                    candidates=[], ambiguous=False)

        if preferred_class:
            filtered = [m for m in matches if m["class_name"] == preferred_class]
            if filtered:
                return RetrievalResult(query=method_name, found=True,
                                        candidates=filtered, ambiguous=False)

        return RetrievalResult(
            query=method_name, found=True, candidates=matches,
            ambiguous=len(matches) > 1,
        )

    def find_by_class_and_method(self, class_name: str, method_name: str) -> dict | None:
        matches = self.symbol_index.get(method_name, [])
        for m in matches:
            if m["class_name"] == class_name:
                return m
        return None
```

### 25.4 حل حالات الغموض (Ambiguity)

عندما توجد أكثر من method بنفس الاسم في كلاسات مختلفة (شائع جدًا — مثل `enforce`)، لا نفترض تلقائيًا الأقرب. بدلًا من ذلك:

```python
def resolve_best_candidate(
    result: RetrievalResult, calling_class_hint: str | None,
    calling_package_hint: str | None
) -> dict | None:
    """استراتيجية بسيطة لكسر الغموض:
    1. لو preferred_class أُعطي وطابق، اخترناه بالفعل في find_method.
    2. غير ذلك: نفضّل candidate من نفس package (استنتاجًا من مسار الملف).
    3. غير ذلك: نرجع None ونترك القرار كـ'unresolved' — أفضل من تخمين خاطئ.
    """
    if not result.found:
        return None
    if len(result.candidates) == 1:
        return result.candidates[0]

    if calling_package_hint:
        same_package = [
            c for c in result.candidates
            if calling_package_hint in c["file_path"]
        ]
        if len(same_package) == 1:
            return same_package[0]

    return None  # غموض حقيقي — يُترَك insufficient_context لاحقًا بدل تخمين
```

> **قاعدة تصميمية:** غموض في الاسترجاع لا يجب أن يتحول أبدًا لتخمين صامت. لو `resolve_best_candidate` أرجع `None`، هذا يُسجَّل صراحة في الـcontext النهائي كـ"لم يتم العثور على تعريف قاطع لـX" — وهذا بالضبط ما يجب أن يقود النموذج لاحقًا لإصدار حكم `insufficient_context` بدل الافتراض.

---

## الفصل 26: Context Builder

هذا هو المكوّن الذي يجمع كل شيء: الـCandidate نفسه (الفصل 22)، ما جلبه الـRetriever (هذا الفصل)، ونتائج الـCall Graph (الفصل 24) — ضمن ميزانية Token محددة، جاهزًا ليصبح Prompt فعلي للنموذج (الفصل 47 لاحقًا).

### 26.1 ميزانية السياق (Context Budget) — تجريبية

| الجزء | النسبة المقترحة | لماذا |
|---|---|---|
| Current method (الـCandidate نفسه) | 25% | جوهر التحليل — لا يمكن اختصاره |
| Caller (من استدعى هذه الـmethod) | 20% | مهم لمعرفة هل تحقق سابق حدث قبل الوصول هنا |
| Security helper (تعريفات مسترجَعة) | 20% | أهم عنصر لحل حالات Ambiguous (الفصل 5.4) |
| Sink method (إن كانت قابلة للجلب) | 20% | يوضح فعليًا حساسية العملية المستهدفة |
| Annotations/AIDL | 10% | سياق تعريف الواجهة الأصلية |
| Metadata (نسخة Android، مسار الملف) | 5% | يفيد الحكم النهائي لكن لا يحتاج مساحة كبيرة |

> **هذه النسب تجريبية بصراحة.** ستُعدَّل لاحقًا بناءً على نتائج الـBaseline (الفصل 42) — مثلًا لو تبيّن أن غياب الـSink تحديدًا يسبب أخطاء أكثر من غياب الـCaller، نرفع نسبته على حساب الآخر.

### 26.2 `context_builder/token_budget.py`

```python
# context_builder/token_budget.py
"""
حساب Token تقريبي (heuristic) بدون تحميل tokenizer كامل في هذه
المرحلة المبكرة — نستخدم تقريب 1 token ≈ 4 أحرف للإنجليزية/الكود،
وهذا كافٍ لتقسيم الميزانية بشكل تقريبي معقول. الفصل 46 (SFT script)
سيستخدم الـtokenizer الفعلي للنموذج المختار عند القياس الدقيق.
"""

CHARS_PER_TOKEN_ESTIMATE = 4

def estimate_tokens(text: str) -> int:
    return max(1, len(text) // CHARS_PER_TOKEN_ESTIMATE)

def truncate_to_token_budget(text: str, max_tokens: int) -> str:
    max_chars = max_tokens * CHARS_PER_TOKEN_ESTIMATE
    if len(text) <= max_chars:
        return text
    # نقطع من المنتصف مع الحفاظ على البداية والنهاية (غالبًا الأهم:
    # توقيع الـmethod في البداية، والـreturn/closing brace في النهاية)
    head = text[: max_chars // 2]
    tail = text[-(max_chars // 2):]
    return f"{head}\n\n... [TRUNCATED] ...\n\n{tail}"
```

### 26.3 `context_builder/builder.py`

```python
# context_builder/builder.py
from dataclasses import dataclass, field
from context_builder.token_budget import estimate_tokens, truncate_to_token_budget

@dataclass
class BudgetAllocation:
    current_method: int
    caller: int
    security_helper: int
    sink: int
    annotations: int
    metadata: int

def default_allocation(total_budget: int) -> BudgetAllocation:
    return BudgetAllocation(
        current_method=int(total_budget * 0.25),
        caller=int(total_budget * 0.20),
        security_helper=int(total_budget * 0.20),
        sink=int(total_budget * 0.20),
        annotations=int(total_budget * 0.10),
        metadata=int(total_budget * 0.05),
    )

@dataclass
class AssembledContext:
    sections: dict[str, str] = field(default_factory=dict)
    unresolved_notes: list[str] = field(default_factory=list)
    total_estimated_tokens: int = 0

def build_context(
    candidate_source: str,
    caller_source: str | None,
    security_helper_sources: dict[str, str | None],  # name -> source or None
    sink_source: str | None,
    aidl_or_annotations: str | None,
    metadata: dict,
    total_budget: int = 3000,
) -> AssembledContext:
    budget = default_allocation(total_budget)
    ctx = AssembledContext()

    ctx.sections["current_method"] = truncate_to_token_budget(
        candidate_source, budget.current_method
    )

    if caller_source:
        ctx.sections["caller"] = truncate_to_token_budget(
            caller_source, budget.caller
        )
    else:
        ctx.sections["caller"] = "[no caller found in local call graph]"

    helper_texts = []
    per_helper_budget = max(
        1, budget.security_helper // max(1, len(security_helper_sources) or 1)
    )
    for name, src in security_helper_sources.items():
        if src is None:
            ctx.unresolved_notes.append(
                f"Definition of '{name}' could not be resolved "
                f"(ambiguous or outside indexed scope)."
            )
            helper_texts.append(f"// {name}: DEFINITION NOT AVAILABLE")
        else:
            helper_texts.append(truncate_to_token_budget(src, per_helper_budget))
    ctx.sections["security_helpers"] = "\n\n".join(helper_texts)

    if sink_source:
        ctx.sections["sink"] = truncate_to_token_budget(sink_source, budget.sink)
    else:
        ctx.sections["sink"] = "[sink method not resolved as separate definition]"

    ctx.sections["annotations"] = truncate_to_token_budget(
        aidl_or_annotations or "[none provided]", budget.annotations
    )

    ctx.sections["metadata"] = truncate_to_token_budget(
        str(metadata), budget.metadata
    )

    ctx.total_estimated_tokens = sum(
        estimate_tokens(v) for v in ctx.sections.values()
    )
    return ctx
```

### 26.4 مثال تجميع كامل

```python
ctx = build_context(
    candidate_source=candidate.source_code,
    caller_source=retrieved_caller.get("source_code") if retrieved_caller else None,
    security_helper_sources={
        "checkCaller": resolved_helper.get("source_code") if resolved_helper else None,
    },
    sink_source=None,  # لم يُحل بعد كـmethod منفصلة
    aidl_or_annotations=None,
    metadata={"android_version": "14", "file": candidate.file},
    total_budget=3000,
)

print(ctx.total_estimated_tokens)   # -> تحقق أنه ضمن حدود معقولة
print(ctx.unresolved_notes)          # -> قائمة صريحة بما لم يُحل، تُمرَّر للنموذج
```

> **لماذا `unresolved_notes` يُمرَّر صراحة للنموذج:** هذا هو الآلية العملية التي تجعل الحكم `insufficient_context` (الفصل 8، القاعدة الثامنة في خلاصة الكتاب) قرارًا مبنيًا على معلومة حقيقية — النموذج **يعرف بالضبط** أنه ينقصه تعريف `checkCaller`، بدل أن يخمّن أو يفترض بصمت.

> **Definition of Done — الجزء الثاني عشر:** بناء context كامل لخمسة Candidates حقيقية من الجزء العاشر، مع تحقق أن `total_estimated_tokens` يبقى ضمن الميزانية المحددة، وأن `unresolved_notes` تعكس فعليًا أي استدعاء أمني لم يُحل عبر الـRetriever.

---

[← الجزء الحادي عشر](./part-11-call-graph.md) · [الفهرس](./README.md) · [الجزء الثالث عشر →](./part-13-dataset-design.md)
