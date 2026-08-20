# download_bge_m3.py
import os
from huggingface_hub import snapshot_download

# 设置镜像
os.environ['HF_ENDPOINT'] = 'https://hf-mirror.com'

# 下载到指定目录
snapshot_download(
    repo_id="BAAI/bge-m3",
    local_dir="/mnt/d/AI_Models/bge-m3",
    local_dir_use_symlinks=False,
    resume_download=True,
    max_workers=4,
)

print("✅ BGE-M3 模型下载完成！")