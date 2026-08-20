# بناء نموذج ذكاء اصطناعي احترافي لاكتشاف ثغرات Android Framework

### من الصفر إلى Android Framework Vulnerability Research Model

دليل تنفيذي كامل: من فهم المشكلة، إلى بناء Dataset خالٍ من التسريب، تدريب QLoRA على جهاز محلي، وبناء Repository Scanner إنتاجي.

> **حالة الإصدار: 📗 الكتاب الأساسي مكتمل (29 جزءًا، 54 فصلًا) + أربعة ملاحق: مصادر البيانات، Teacher Model، معمارية Agent، ومختبر التحقق الديناميكي.**

---

## فهرس الكتاب الكامل

### ✅ [الجزء الأول: تعريف المشروع](./part-01-project-definition.md)
- الفصل 1: ما الذي نبنيه فعلًا؟
- الفصل 2: تعريف النجاح

### ✅ [الجزء الثاني: Android Security Fundamentals](./part-02-android-fundamentals.md)
- الفصل 3: Android Security Architecture
- الفصل 4: AOSP Architecture for Security Research
- الفصل 5: Binder Security Model
- الفصل 6: Android Authorization

### ✅ [الجزء الثالث: Threat Modeling للكود](./part-03-threat-modeling.md)
- الفصل 7: Trust Boundaries
- الفصل 8: Source → Sink Analysis
- الفصل 9: Security Invariants (مكتبة 50 Invariant)

### ✅ [الجزء الرابع: Vulnerability Taxonomy](./part-04-vulnerability-taxonomy.md)
- الفصل 10: Taxonomy الكامل

### ✅ [الجزء الخامس: إعداد بيئة البحث](./part-05-research-environment.md)
- الفصل 11: Linux Environment · الفصل 12: بنية المشروع

### ✅ [الجزء السادس: جمع AOSP](./part-06-aosp-collection.md)
- الفصل 13: تنزيل AOSP · الفصل 14: Repository Metadata

### ✅ [الجزء السابع: Security Patch Mining](./part-07-patch-mining.md)
- الفصل 15: Git History Mining · الفصل 16: Candidate Security Commit Detection · الفصل 17: Before/After Extraction

### ✅ [الجزء الثامن: Android Security Bulletins](./part-08-security-bulletins.md)
- الفصل 18: Bulletin Collector

### ✅ [الجزء التاسع: Parsing](./part-09-parsing.md)
- الفصل 19: Java/Kotlin Parsing · الفصل 20: Security API Extraction

### ✅ [الجزء العاشر: Static Analysis Layer](./part-10-static-analysis.md)
- الفصل 21: Security Facts Extractor · الفصل 22: Candidate Generator

### ✅ [الجزء الحادي عشر: Call Graph](./part-11-call-graph.md)
- الفصل 23: Call Graph · الفصل 24: Multi-Function Security Reasoning

### ✅ [الجزء الثاني عشر: Retrieval](./part-12-retrieval.md)
- الفصل 25: Code Retriever · الفصل 26: Context Builder

### ✅ [الجزء الثالث عشر: Dataset Design](./part-13-dataset-design.md)
- الفصل 27: Dataset Schema · الفصل 28: Dataset Labels

### ✅ [الجزء الرابع عشر: Vulnerable/Fixed Pairs](./part-14-vulnerable-fixed-pairs.md)
- الفصل 29: تحويل Patch إلى Samples

### ✅ [الجزء الخامس عشر: Secure Negatives](./part-15-secure-negatives.md)
- الفصل 30: Negative Samples · الفصل 31: Hard Negative Mining

### ✅ [الجزء السادس عشر: Insufficient Context](./part-16-insufficient-context.md)
- الفصل 32: تعليم النموذج عدم التخمين

### ✅ [الجزء السابع عشر: Provenance](./part-17-provenance.md)
- الفصل 33: Provenance · الفصل 34: PostgreSQL Schema

### ✅ [الجزء الثامن عشر: Deduplication](./part-18-deduplication.md)
- الفصل 35: Duplicate Detection

### ✅ [الجزء التاسع عشر: Leakage Prevention](./part-19-leakage-prevention.md)
- الفصل 36: Train/Test Splitting · الفصل 37: Future Patch Evaluation

### ✅ [الجزء العشرون: Benchmark](./part-20-benchmark.md)
- الفصل 38: Benchmark v0.1 · الفصل 39: Ground Truth

### ✅ [الجزء الحادي والعشرون: اختيار النموذج](./part-21-model-selection.md)
- الفصل 40: Model Selection · الفصل 41: Base vs Instruct

### ✅ [الجزء الثاني والعشرون: Baseline](./part-22-baseline.md)
- الفصل 42: Baseline Before Training

### ✅ [الجزء الثالث والعشرون: QLoRA](./part-23-qlora.md)
- الفصل 43: QLoRA Fundamentals · الفصل 44: VRAM Budget · الفصل 45: Training Config v0.1

### ✅ [الجزء الرابع والعشرون: SFT](./part-24-sft.md)
- الفصل 46: SFT Training Script · الفصل 47: Formatting Training Samples

### ✅ [الجزء الخامس والعشرون: Curriculum](./part-25-curriculum.md)
- الفصل 48: Curriculum Learning

### ✅ [الجزء السادس والعشرون: Synthetic Data](./part-26-synthetic-data.md)
- الفصل 49: Synthetic Data · الفصل 50: Teacher Model Workflow

### ✅ [الجزء السابع والعشرون: Quality Scoring](./part-27-quality-scoring.md)
- الفصل 51: Sample Quality

### ✅ [الجزء الثامن والعشرون: Evaluation](./part-28-evaluation.md)
- الفصل 52: Automated Evaluation · الفصل 53: Semantic Evaluation

### ✅ [الجزء التاسع والعشرون: Confidence Calibration وما بعدها](./part-29-calibration-and-beyond.md)
- الفصل 54: Calibration · خارطة التنفيذ الكاملة (Milestones 0-8) · المعمارية النهائية · قواعد المشروع · الخاتمة

---

## ملحق: مصادر البيانات وTeacher Model (إضافة تفصيلية)

### ✅ [الجزء الثلاثون: التعمق في مصادر البيانات](./part-30-data-sources-deep-dive.md)
- الفصل 55: مصدر 1 — كود AOSP · الفصل 56: مصدر 2 — Patch Mining · الفصل 57: مصدر 3 — Security Bulletins · الفصل 58: مصدر 4 — Hard Negative Mining · الفصل 59: مصدر 5 — Synthetic Generation (مع رسم بياني لكل مصدر)

### ✅ [الجزء الحادي والثلاثون: اختيار وربط Teacher Model](./part-31-teacher-model.md)
- الفصل 60: معايير الاختيار والمقارنة الفعلية (DeepSeek V4 / Claude / GPT-5.4 / Qwen3.5) · الفصل 61: الربط الفعلي بالـPipeline (كود تكامل كامل + تقدير تكلفة)

### ✅ [الجزء الثاني والثلاثون: معمارية Agent لاكتشاف الثغرات](./part-32-agent-architecture.md)
- الفصل 62: قرار المعمارية (Teacher-tier Agent فوق البنية الحالية) · الفصل 63: تعريف الأدوات الخمس (retrieve_definition, trace_variable, query_call_graph, check_patch_history, verify_claim_against_facts) · الفصل 64: حلقة الـAgent، الحدود، وسياسة التكلفة

### ✅ [الجزء الثالث والثلاثون: مختبر التحقق الديناميكي](./part-33-dynamic-verification-lab.md)
- الفصل 65: تصميم المختبر (Android Emulator محلي، userdebug) · الفصل 66: توليد تطبيق الاختبار تلقائيًا · الفصل 67: التشغيل، المراقبة عبر Frida، وتفسير النتائج (Lab Verdict → Ground Truth)

> **نطاق حصري:** المختبر يعمل فقط على AOSP محلي داخل Emulator على جهازك — لا يتصل بأي نظام خارجي ولا يستهدف مواقع أو خدمات إنتاجية حقيقية.
