[← الجزء السادس عشر](./part-16-insufficient-context.md) · [الفهرس](./README.md)

# الجزء السابع عشر: Provenance

## الفصل 33: Provenance

كل الفصول السابقة أنتجت بيانات (commits، candidates، samples) موزَّعة عبر ملفات JSONL منفصلة. مع نمو المشروع، تتبّع "من أين جاءت هذه العينة، وماذا حدث لها" يدويًا عبر ملفات نصية يصبح غير عملي. هذا الفصل يحدد **الحد الأدنى الإلزامي** من معلومات النسب (provenance) لكل عينة، تمهيدًا لنقلها إلى قاعدة بيانات فعلية (الفصل 34).

### 33.1 القاعدة الصارمة: لا Sample بدون Provenance كامل

كل عينة — بصرف النظر عن مصدرها (patch-derived، hard negative، crafted insufficient-context، synthetic لاحقًا في الفصل 49) — **يجب** أن تحمل:

| الحقل | لماذا إلزامي |
|---|---|
| `source repo` + `commit` | تتبّع الأصل الدقيق لإعادة التوليد أو التحقق لاحقًا |
| `path` + `method` | تحديد الموقع الدقيق داخل الـrepo |
| `generation_method` | (من enum الفصل 27.4) — يحدد المسار الذي أنتج هذه العينة تحديدًا |
| `reviewer` | من (أو ماذا) راجع هذه العينة — `manual_v1`, `auto_draft_v1`, أو اسم مراجع بشري فعلي |
| `label_confidence` | ثقة المصدر نفسه في التصنيف، منفصلة عن `analysis.confidence` (التي هي ثقة النموذج المستقبلي أثناء الاستدلال) |

> **تمييز مهم:** `provenance.label_confidence` ≠ `analysis.confidence`. الأول هو تقييم بشري/نظامي لجودة عملية التصنيف نفسها وقت إنشاء العينة. الثاني هو ما يُتوقَّع أو يُقاس من النموذج أثناء الاستدلال على عينة مشابهة لاحقًا. الخلط بينهما يُفسِد كلا الاستخدامين.

### 33.2 مشكلة الاعتماد على ملفات JSONL وحدها

- لا يوجد فرض تلقائي لتفرد `sample_id` عبر ملفات متعددة.
- لا يمكن الاستعلام بسهولة عن "كل العينات المشتقة من commit معيّن" أو "كل العينات التي راجعها فلان" دون كتابة سكريبت مخصص لكل استعلام.
- لا آلية مركزية لمنع تكرار نفس الـcommit في أكثر من split (يتصل مباشرة بمشكلة Data Leakage — الفصل 36).

هذه المشاكل الثلاث هي بالضبط ما يحله الفصل التالي.

---

## الفصل 34: PostgreSQL Schema

### 34.1 لماذا PostgreSQL وليس مجرد ملفات JSONL دائمًا

PostgreSQL (المثبتة أصلًا في الفصل 11) تصبح ضرورية بمجرد أن يتجاوز المشروع مرحلة النموذج الأولي — تحديدًا عند الحاجة لـ: فرض قيود تفرّد (unique constraints)، استعلامات معقّدة عبر الجداول (مثل الفصل 36: Train/Test splitting)، وتتبّع تاريخ التجارب (الفصل 39 وما بعده).

### 34.2 مخطط الجداول

```sql
-- db/schema.sql

CREATE TABLE repositories (
    id              SERIAL PRIMARY KEY,
    project         TEXT NOT NULL,          -- e.g. 'frameworks/base'
    android_version TEXT NOT NULL,
    tag             TEXT,
    local_path      TEXT,
    fetched_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (project, android_version)
);

CREATE TABLE commits (
    id              SERIAL PRIMARY KEY,
    repository_id   INTEGER NOT NULL REFERENCES repositories(id),
    commit_hash     TEXT NOT NULL,
    parent_hash     TEXT,
    author_date     TIMESTAMPTZ,
    subject         TEXT,
    body            TEXT,
    candidate_score REAL,                    -- من الفصل 16
    UNIQUE (repository_id, commit_hash)
);

CREATE TABLE cve_bulletins (
    id                  SERIAL PRIMARY KEY,
    cve_id              TEXT NOT NULL UNIQUE,
    bulletin_date       DATE,
    severity            TEXT,
    component           TEXT,
    affected_versions   TEXT[],
    source_bulletin_url TEXT
);

CREATE TABLE commit_cve_links (
    commit_id   INTEGER NOT NULL REFERENCES commits(id),
    cve_id      INTEGER NOT NULL REFERENCES cve_bulletins(id),
    resolved    BOOLEAN NOT NULL DEFAULT false,
    PRIMARY KEY (commit_id, cve_id)
);

CREATE TABLE methods (
    id              SERIAL PRIMARY KEY,
    commit_id       INTEGER NOT NULL REFERENCES commits(id),
    file_path       TEXT NOT NULL,
    class_name      TEXT NOT NULL,
    method_name     TEXT NOT NULL,
    start_line      INTEGER,
    end_line        INTEGER,
    source_code     TEXT NOT NULL,
    snapshot_side   TEXT NOT NULL CHECK (snapshot_side IN ('before', 'after', 'stable')),
    security_facts  JSONB                    -- مخرجات الفصل 21 كاملة
);

CREATE TABLE samples (
    id                  SERIAL PRIMARY KEY,
    sample_id           TEXT NOT NULL UNIQUE,      -- يطابق DatasetSample.sample_id
    source_method_id    INTEGER REFERENCES methods(id),
    task                TEXT NOT NULL,
    code_context        JSONB NOT NULL,
    analysis            JSONB NOT NULL,
    verdict             TEXT NOT NULL CHECK (
        verdict IN ('vulnerable', 'secure', 'ambiguous', 'insufficient_context')
    ),
    generation_method   TEXT NOT NULL,
    reviewer            TEXT NOT NULL,
    label_confidence    TEXT NOT NULL CHECK (label_confidence IN ('high','medium','low')),
    quality_score       INTEGER CHECK (quality_score BETWEEN 0 AND 30),
    dataset_version      TEXT,                       -- e.g. 'v0.1', 'v0.2' (الفصل 40)
    split                TEXT CHECK (split IN ('train', 'validation', 'test', 'benchmark')),
    created_at            TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE benchmark_cases (
    id              SERIAL PRIMARY KEY,
    sample_id       INTEGER NOT NULL REFERENCES samples(id),
    category        TEXT,                    -- من Taxonomy الفصل 10
    difficulty      TEXT,                    -- من Curriculum الفصل 48
    added_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE model_runs (
    id                  SERIAL PRIMARY KEY,
    run_label           TEXT NOT NULL UNIQUE,   -- e.g. 'AFVRM-7B-v0.1'
    base_model          TEXT NOT NULL,
    dataset_version      TEXT NOT NULL,
    training_config      JSONB,
    git_commit           TEXT,                   -- كود المشروع نفسه وقت التدريب
    started_at           TIMESTAMPTZ,
    completed_at         TIMESTAMPTZ
);

CREATE TABLE evaluations (
    id              SERIAL PRIMARY KEY,
    model_run_id    INTEGER NOT NULL REFERENCES model_runs(id),
    benchmark_case_id INTEGER NOT NULL REFERENCES benchmark_cases(id),
    predicted_verdict      TEXT,
    predicted_location     TEXT,
    predicted_confidence   REAL,
    raw_model_output        JSONB,
    is_correct_verdict       BOOLEAN,
    evaluated_at              TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE failures (
    id              SERIAL PRIMARY KEY,
    model_run_id    INTEGER NOT NULL REFERENCES model_runs(id),
    sample_id       INTEGER REFERENCES samples(id),
    expected         TEXT,
    actual           TEXT,
    failure_type      TEXT,                  -- من تصنيف الفصل 38 لاحقًا
    root_cause_note   TEXT,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- فهارس أساسية للاستعلامات الشائعة
CREATE INDEX idx_commits_hash ON commits(commit_hash);
CREATE INDEX idx_samples_split ON samples(dataset_version, split);
CREATE INDEX idx_samples_verdict ON samples(verdict);
CREATE INDEX idx_methods_commit ON methods(commit_id);
```

### 34.3 لماذا `code_context` و`analysis` كأعمدة JSONB وليست جداول مفصَّلة

القرار مقصود: هذان الحقلان غنيا البنية ويتغيران بمرونة (حقول جديدة قد تُضاف لاحقًا — مثل الفصل 54: Confidence Calibration قد يضيف حقول معايرة إضافية). تطبيعهما (normalization) بالكامل لجداول SQL منفصلة يزيد التعقيد دون فائدة استعلامية حقيقية في هذه المرحلة. PostgreSQL's JSONB يسمح بالاستعلام داخل هذه الحقول عند الحاجة (`analysis->>'trust_boundary'`) دون التضحية بالمرونة.

### 34.4 الاتصال من Python (`db/connection.py`)

```python
# db/connection.py
import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

def get_engine():
    password = os.environ["AFVRM_DB_PASSWORD"]  # لا كلمات مرور في الكود مطلقًا
    url = f"postgresql+psycopg2://afvrm:{password}@localhost:5432/afvrm_db"
    return create_engine(url)

def get_session():
    engine = get_engine()
    Session = sessionmaker(bind=engine)
    return Session()
```

### 34.5 مثال: نقل عينات JSONL موجودة إلى قاعدة البيانات

```python
# db/migrate_jsonl_to_db.py
import json
from pathlib import Path
from sqlalchemy import text
from db.connection import get_engine

def migrate_samples(jsonl_path: Path, dataset_version: str, split: str):
    engine = get_engine()
    inserted, skipped = 0, 0

    with engine.begin() as conn, jsonl_path.open() as f:
        for line in f:
            sample = json.loads(line)
            try:
                conn.execute(text("""
                    INSERT INTO samples (
                        sample_id, task, code_context, analysis, verdict,
                        generation_method, reviewer, label_confidence,
                        quality_score, dataset_version, split
                    ) VALUES (
                        :sample_id, :task, :code_context, :analysis, :verdict,
                        :generation_method, :reviewer, :label_confidence,
                        :quality_score, :dataset_version, :split
                    )
                    ON CONFLICT (sample_id) DO NOTHING
                """), {
                    "sample_id": sample["sample_id"],
                    "task": sample["task"],
                    "code_context": json.dumps(sample["code_context"]),
                    "analysis": json.dumps(sample["analysis"]),
                    "verdict": sample["verdict"],
                    "generation_method": sample["provenance"]["generation_method"],
                    "reviewer": sample["provenance"]["reviewer"],
                    "label_confidence": sample["provenance"]["label_confidence"],
                    "quality_score": sample["provenance"]["quality_score"],
                    "dataset_version": dataset_version,
                    "split": split,
                })
                inserted += 1
            except Exception as e:
                print(f"Skipped {sample.get('sample_id')}: {e}")
                skipped += 1

    print(f"Migrated: {inserted} inserted, {skipped} skipped")

if __name__ == "__main__":
    migrate_samples(
        Path("sample_generator/output/android-14_draft_samples.jsonl"),
        dataset_version="v0.1", split="train",
    )
```

> **ملاحظة على الأمان:** لاحظ استخدام `text()` مع named parameters (`:sample_id`) بدل f-string concatenation — هذا يمنع SQL injection بغض النظر عن مصدر البيانات، حتى لو كانت من مصدر "موثوق" نظريًا مثل ملفات المشروع الداخلية.

> **Definition of Done — الجزء السابع عشر:** قاعدة البيانات تحتوي فعليًا كل الجداول أعلاه، مع نقل ناجح لعينة حقيقية من ملفات JSONL سابقة (الفصل 29، 31) دون فقدان بيانات، واستعلام تجريبي ناجح مثل: `SELECT verdict, COUNT(*) FROM samples GROUP BY verdict;` يعطي توزيعًا منطقيًا يقارَب التوزيع المستهدف في الفصل 28.4.

---

[← الجزء السادس عشر](./part-16-insufficient-context.md) · [الفهرس](./README.md) · [الجزء الثامن عشر →](./part-18-deduplication.md)
