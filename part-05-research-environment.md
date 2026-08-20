[← الجزء الرابع](./part-04-vulnerability-taxonomy.md) · [الفهرس](./README.md)

# الجزء الخامس: إعداد بيئة البحث

## الفصل 11: Linux Environment

هذا الفصل يجهّز البيئة الفعلية على الجهاز المستهدف (i7-14700K / RTX 5070 Ti / 16GB VRAM / 32GB RAM / Ubuntu). كل أمر هنا قابل للتنفيذ حرفيًا.

### 11.1 تحديث النظام والأدوات الأساسية

```bash
sudo apt update && sudo apt upgrade -y

sudo apt install -y \
    build-essential git curl wget unzip \
    software-properties-common \
    ripgrep jq \
    postgresql postgresql-contrib \
    python3.12 python3.12-venv python3-pip
```

### 11.2 تثبيت `uv` (إدارة بيئات Python أسرع من pip/venv التقليدي)

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
source $HOME/.local/bin/env

uv --version
```

### 11.3 إنشاء بيئة المشروع

```bash
mkdir -p ~/android-vuln-llm && cd ~/android-vuln-llm
uv venv --python 3.12
source .venv/bin/activate
```

### 11.4 تثبيت CUDA وPyTorch

```bash
# تحقق من دعم الكارت لأحدث CUDA المتاح للـdriver المثبت
nvidia-smi

# تثبيت PyTorch بدعم CUDA (استخدم الأمر المطابق لإصدار CUDA الظاهر في nvidia-smi
# من https://pytorch.org/get-started/locally/)
uv pip install torch --index-url https://download.pytorch.org/whl/cu124
```

### 11.5 مكتبات التدريب والتقييم

```bash
uv pip install \
    transformers \
    datasets \
    accelerate \
    peft \
    trl \
    bitsandbytes \
    sentencepiece \
    einops \
    tree-sitter \
    tree-sitter-languages \
    psycopg2-binary \
    sqlalchemy \
    pydantic \
    tqdm \
    rich
```

### 11.6 PostgreSQL — إعداد أولي

```bash
sudo -u postgres psql -c "CREATE USER afvrm WITH PASSWORD 'change_me';"
sudo -u postgres psql -c "CREATE DATABASE afvrm_db OWNER afvrm;"
```

> غيّر `change_me` فعليًا، ولا تضعه في أي ملف يُرفع لـ Git — استخدم متغير بيئة `AFVRM_DB_PASSWORD` بدلًا من ذلك.

### 11.7 سكريبت التحقق (`scripts/check_env.py`)

هذا السكريبت هو أول شيء يجب أن ينجح قبل الاستمرار في أي خطوة لاحقة.

```python
# scripts/check_env.py
import subprocess
import sys

def section(title: str):
    print(f"\n{'=' * 10} {title} {'=' * 10}")

def check_gpu():
    section("GPU")
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total,driver_version",
             "--format=csv,noheader"],
            capture_output=True, text=True, check=True
        )
        print(out.stdout.strip())
    except Exception as e:
        print(f"FAILED: nvidia-smi not available ({e})")
        sys.exit(1)

def check_torch():
    section("PyTorch / CUDA")
    import torch
    print(f"torch version:      {torch.__version__}")
    print(f"cuda available:     {torch.cuda.is_available()}")
    if not torch.cuda.is_available():
        print("FAILED: CUDA not available to PyTorch")
        sys.exit(1)
    print(f"device name:        {torch.cuda.get_device_name(0)}")
    print(f"total VRAM (GB):    {torch.cuda.get_device_properties(0).total_memory / 1e9:.1f}")
    print(f"bf16 supported:     {torch.cuda.is_bf16_supported()}")

def check_packages():
    section("Key packages")
    import importlib
    required = [
        "transformers", "datasets", "accelerate",
        "peft", "trl", "bitsandbytes", "psycopg2",
    ]
    for pkg in required:
        try:
            mod = importlib.import_module(pkg)
            ver = getattr(mod, "__version__", "unknown")
            print(f"{pkg:<15} {ver}")
        except ImportError:
            print(f"{pkg:<15} MISSING")
            sys.exit(1)

def check_training_smoke_test():
    section("Training smoke test (tiny matmul on GPU)")
    import torch
    a = torch.randn(4096, 4096, device="cuda", dtype=torch.bfloat16)
    b = torch.randn(4096, 4096, device="cuda", dtype=torch.bfloat16)
    c = a @ b
    torch.cuda.synchronize()
    print(f"matmul OK, result shape: {tuple(c.shape)}, dtype: {c.dtype}")

if __name__ == "__main__":
    check_gpu()
    check_torch()
    check_packages()
    check_training_smoke_test()
    section("ALL CHECKS PASSED")
```

تشغيل:

```bash
python scripts/check_env.py
```

> **Definition of Done — الفصل 11:** السكريبت أعلاه يطبع `ALL CHECKS PASSED` بدون أي استثناء. لا ننتقل لأي خطوة تالية قبل ذلك.

---

## الفصل 12: بنية المشروع

البنية التالية هي الهيكل الكامل الذي ستُبنى عليه كل الفصول القادمة. كل مجلد له مسؤولية واحدة واضحة (Single Responsibility)، بما يعكس المعمارية الموصوفة في الفصل 1.

```
android-vuln-llm/
│
├── collector/            # تنزيل AOSP ومزامنة الإصدارات (الجزء 6)
├── patch_miner/           # استخراج commits أمنية من تاريخ Git (الجزء 7)
├── parser/                 # AST parsing لـJava/Kotlin (الجزء 9)
├── security_rules/         # قائمة الـSecurity APIs القابلة للتهيئة (الفصل 20)
├── candidate_generator/    # قواعد ترشيح المواقع المشبوهة (الجزء 10)
├── context_builder/        # بناء context محدود الميزانية للـLLM (الفصل 26)
├── retriever/               # Code Retriever — بحث lexical/symbol (الفصل 25)
├── normalizer/              # تطبيع الكود قبل المقارنة/الـdedup
├── sample_generator/        # تحويل patches إلى training samples (الجزء 14)
├── quality/                  # Quality scoring للعينات (الفصل 51)
├── dedup/                    # كشف التكرار (الفصل 35)
├── dataset/                  # ملفات JSONL النهائية + versions
├── benchmark/                 # حالات الاختبار المستقلة (الجزء 20)
├── training/                   # سكريبتات QLoRA/SFT (الجزء 24، 26)
├── evaluation/                  # مقاييس وتقييم آلي (الفصل 2، 52، 53)
├── inference/                    # تشغيل النموذج المدرَّب
├── scanner/                       # Repository Scanner النهائي (الجزء الأخير)
├── configs/                        # ملفات YAML للتجارب
├── scripts/                         # أدوات مساعدة (مثل check_env.py)
├── tests/                            # اختبارات وحدة لكل مكوّن
├── docs/                              # توثيق داخلي إضافي
└── experiments/                        # سجلات كل تجربة تدريب (versioned)
```

### 12.1 وظيفة كل مجلد بالتفصيل

| المجلد | يستقبل | ينتج | يُستخدم في |
|---|---|---|---|
| `collector/` | لا شيء (نقطة البداية) | نسخ AOSP محلية + metadata | الفصل 13 |
| `patch_miner/` | مستودعات `collector/` | Candidate security commits + diffs | الفصل 15–17 |
| `parser/` | ملفات `.java`/`.kt` | AST + symbol table | الفصل 19 |
| `security_rules/` | — (تهيئة ثابتة) | قائمة APIs مستهدفة | الفصل 20، 21 |
| `candidate_generator/` | Security Facts من `parser/` | قائمة Candidates بـscore | الفصل 22 |
| `context_builder/` | Candidate + نتائج `retriever/` | Context جاهز للنموذج | الفصل 26 |
| `retriever/` | استعلام (method/class) | تعريفات مرتبطة | الفصل 25 |
| `sample_generator/` | patch واحد + metadata | عدة training samples | الفصل 29 |
| `quality/` | sample خام | sample + quality score | الفصل 51 |
| `dedup/` | مجموعة samples | مجموعة بلا تكرار | الفصل 35 |
| `dataset/` | مخرجات `dedup/` بعد الموافقة | ملفات JSONL versioned | الفصل 27، 40 |
| `benchmark/` | مجموعة فرعية معزولة من الـdataset | حالات اختبار ثابتة | الفصل 38 |
| `training/` | `dataset/` + `configs/` | LoRA adapter checkpoints | الفصل 43–48 |
| `evaluation/` | نموذج + `benchmark/` | تقرير مقاييس | الفصل 2، 52 |
| `scanner/` | مستودع AOSP كامل + نموذج مدرَّب | تقرير Findings نهائي | الجزء الأخير |

### 12.2 إعداد المستودع الأولي

```bash
cd ~/android-vuln-llm
mkdir -p collector patch_miner parser security_rules candidate_generator \
         context_builder retriever normalizer sample_generator quality \
         dedup dataset benchmark training evaluation inference scanner \
         configs scripts tests docs experiments

git init
cat > .gitignore << 'EOF'
.venv/
__pycache__/
*.pyc
dataset/*.jsonl
experiments/*/checkpoints/
aosp_sources/
.env
EOF

git add .
git commit -m "chore: initial project structure"
```

> **ملاحظة مهمة:** مصادر AOSP نفسها (`aosp_sources/` أو ما يعادله) **لا تُرفع أبدًا** لـ Git — حجمها يجعل ذلك غير عملي، وترخيصها لا يتطلب ذلك. فقط الكود المُنتَج (collectors, parsers, samples المُشتقة بعد المعالجة) هو ما يُنسَّخ بالإصدارات.

> **Definition of Done — الفصل 12:** البنية أعلاه موجودة فعليًا على القرص، `git log` يظهر أول commit، و`.gitignore` يمنع رفع أي مصدر AOSP خام أو بيانات اعتماد.

---

[← الجزء الرابع](./part-04-vulnerability-taxonomy.md) · [الفهرس](./README.md) · [الجزء السادس →](./part-06-aosp-collection.md)
