@echo off
rem Voice Crucible: keeps Python, packages, caches and models inside this folder (nothing goes elsewhere).
set "VC=%~dp0"
set "VC_UV=%VC%uv.exe"
if not exist "%VC_UV%" set "VC_UV=uv"
set "UV_PYTHON_INSTALL_DIR=%VC%runtime\python"
set "UV_CACHE_DIR=%VC%runtime\uv-cache"
set "UV_PROJECT_ENVIRONMENT=%VC%runtime\venv"
set "UV_PYTHON_PREFERENCE=only-managed"
set "HF_HOME=%VC%runtime\models\huggingface"
set "TORCH_HOME=%VC%runtime\models\torch"
set "XDG_CACHE_HOME=%VC%runtime\models"
