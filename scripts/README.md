# AWS Resources

### Set Up Python Virtual Environment

Open your terminal in your project directory and run the following commands:

1. **Create the virtual environment** (named `.venv`):
```bash
python -m venv .venv

```

2. **Activate the virtual environment**:
* **macOS / Linux:**
```bash
source .venv/bin/activate

```

* **Windows (Command Prompt):**
```cmd
.venv\Scripts\activate.bat

```

* **Windows (PowerShell):**
```powershell
.venv\Scripts\Activate.ps1

```

### Install Dependencies and Run the Script

Choose your preferred package installer below:

#### Option A: Using Standard `pip` (Built-in & Reliable)

`pip` comes pre-installed with Python and is the traditional tool for managing packages.

1. Upgrade pip and install requirements:
```bash
pip install --upgrade pip
pip install -r requirements.txt

```


2. Execute the script:
```bash
python multi_vpc_manager.py --region us-east-1 --read

```

---

#### Option B: Using `uv` (Extremely Fast & Modern)

`uv` is written in Rust by Astral (creators of Ruff) and acts as an extremely fast drop-in replacement for pip/virtualenv.

1. Install `uv` (if you don't already have it):
* **macOS / Linux:** `curl -sSf [https://astral.sh/uv/install.sh](https://astral.sh/uv/install.sh) | sh`
* **Windows:** `powershell -c "irm [https://astral.sh/uv/install.ps1](https://astral.sh/uv/install.ps1) | iex"`


2. Install dependencies using `uv` (it takes less than a second):
```bash
uv pip install -r requirements.txt

```


3. Execute the script:
```bash
python multi_vpc_manager.py --region us-east-1 --read

```

Deactivate Session as below to close virtual env session:

```bash
deactivate
```

---

### Pip vs. `uv`: Which is better?

| Feature | Standard `pip` | `uv` |
| --- | --- | --- |
| **Speed** | Moderate (downloads and builds packages sequentially). | **Blazing fast** (written in Rust, highly optimized parallel downloads). |
| **Setup** | Built right into Python by default. No extra installation needed. | Requires a one-time quick installation tool. |
| **Compatibility** | Universal standard across almost all Python tutorials and servers. | Fully compatible with standard `pip` commands and `requirements.txt`. |

* **Recommendation:** Use **`pip`** if you want something standard that requires zero extra installation steps. Use **`uv`** if you work with Python frequently and prefer a modern tool that installs packages almost instantly.

Would you like help setting up AWS credentials (like configuring your AWS CLI profile) before running the script?