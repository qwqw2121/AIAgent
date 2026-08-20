from huggingface_hub import snapshot_download

snapshot_download(
    repo_id="BAAI/bge-m3",
    local_dir="/mnt/d/AI_Models/bge-m3",
    local_dir_use_symlinks=False,
    ignore_patterns=["*.pt", "*.h5"]  # 不下载无关文件
)