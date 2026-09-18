

```bash
nc -zv -w 5 <ec2-public-ip> 22
```


This error occurs because **Claude Code expects Anthropic-formatted tool calling / system messages**, whereas Ollama’s raw OpenAI compatibility endpoint (`/v1`) doesn't automatically map Claude's structured parameters unless routed correctly or aliased.

In addition, when using `ANTHROPIC_BASE_URL` with custom Anthropic-compatible local proxies, Claude Code validates model naming and endpoint routing strictly.

---

#### Systemd Override (EC2 Server-Side)

SSH into your EC2 instance:

```bash
ssh -i private_key.pem ubuntu@3.145.43.228

```

Edit the systemd override file to set `OLLAMA_CONTEXT_LENGTH`:

```bash
sudo mkdir -p /etc/systemd/system/ollama.service.d
sudo tee /etc/systemd/system/ollama.service.d/override.conf <<'EOF'
[Service]
Environment="OLLAMA_MAX_LOADED_MODELS=1"
Environment="OLLAMA_NUM_PARALLEL=1"
Environment="OLLAMA_KEEP_ALIVE=15m"
Environment="OLLAMA_CONTEXT_LENGTH=32768"
EOF

sudo systemctl daemon-reload
sudo systemctl restart ollama

```

#### Create a Custom Modelfile in Ollama

Verify Model Name Exists in Ollama by checking if `qwq:32k` actually appears in your local list:

```bash
ollama list
```

Ollama locks individual model configurations unless explicitly declared in a Modelfile. Create a custom version of `qwq` with a 32k context size parameter baked into it:

SSH into your instance and run:

```bash
# Create a custom Modelfile
cat <<'EOF' > Modelfile
FROM qwq
PARAMETER num_ctx 32768
EOF

# Create a new custom model tag 'qwq:32k'
ollama create qwq:32k -f Modelfile

```

---

### Setup LiteLLM Proxy (Alternate Solution)

Claude Code relies on Anthropic's specific message schema (`/v1/messages`), whereas Ollama natively serves OpenAI's schema (`/v1/chat/completions`). Passing raw Ollama endpoints into Claude CLI often yields model resolution or 400 validation errors.

The cleanest fix is running **LiteLLM** directly on your EC2 instance. It acts as an adapter that converts Claude's native API requests into Ollama calls effortlessly.

#### 1. Install & Launch LiteLLM on EC2

SSH into your EC2 instance and run. Use `11434` for ollama or `4000` for LiteLLM:

```bash
# Install litellm
pip install litellm

# Create a simple config file
cat <<'EOF' > config.yaml
model_list:
  - model_name: qwq:32k
    litellm_params:
      model: ollama/qwq:32k
      api_base: http://127.0.0.1:11434
EOF

# Start LiteLLM proxy listening on port 4000
nohup litellm --config config.yaml --port 4000 > /var/log/litellm.log 2>&1 &

```

---

### Update SSH Tunneling & Local Settings

#### 1. Open SSH Tunnel to Port 4000 (LiteLLM)

Run the SSH tunnel pointing to port `11434` for Ollama or port `4000` for LiteLLM:

```bash
ssh -i private_key.pem -N -L 4000:localhost:4000 ubuntu@3.145.43.219

```

#### Update `settings-ollama.json`

- Update your local `settings-ollama.json`:

    ```json
    {
    "env": {
        "ANTHROPIC_BASE_URL": "http://localhost:11434/v1",
        "ANTHROPIC_API_KEY": "ollama"
    }
    }
    ```

- Update your local `settings-ollama-litellm.json`:

    ```json
    {
    "env": {
        "ANTHROPIC_BASE_URL": "http://localhost:4000",
        "ANTHROPIC_API_KEY": "sk-1234"
    }
    }
    ```

### Launch Claude CLI

Execute Claude CLI referencing the mapped model:

```bash
claude --settings ./settings-ollama.json --model qwq:32k

```

---

### Troubleshooting Steps

Check if UserData finished running

```bash
tail -n 30 /var/log/cloud-init-output.log
```

Check the Ollama Service Status

```bash
sudo systemctl status ollama
```

Verify NVIDIA Drivers are active

```bash
nvidia-smi
```

Enable and Start Ollama by running these commands inside your SSH session:

```bash
sudo systemctl enable --now ollama

```

If the reboot interrupted the initial pull, trigger the model download again:

```bash
nohup sudo -u root ollama pull qwq > /var/log/ollama_pull.log 2>&1 &

```

Check the service journal to ensure Ollama now detects your A10G GPU:

```bash
journalctl -u ollama --no-pager -n 30

```

The model pull runs asynchronously in the background during initial boot. Track the model download progress using below command:

```bash
tail -f /var/log/ollama_pull.log

```
