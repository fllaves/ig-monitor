"""Análisis local de imágenes de historias con Ollama.

**Todo corre en tu Mac**: la imagen se envía a `localhost:11434`, se procesa
con un modelo local y el resultado se guarda. Nada sale a internet, ningún
servidor externo ve las fotos (ni las de ellas ni las tuyas).

Uso:
    python3 vision.py data/stories/BC_123.jpg
"""
import base64
import json
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

# Paquetes instalados dentro del proyecto (ej. imageio-ffmpeg)
_LIB = Path(__file__).resolve().parent / "lib"
if _LIB.is_dir() and str(_LIB) not in sys.path:
    sys.path.insert(0, str(_LIB))

OLLAMA = "http://localhost:11434"
MODELO = "qwen2.5vl:7b"

PROMPT = (
    "Responde SIEMPRE en ESPAÑOL, sin excepciones, aunque el texto de la imagen "
    "esté en otro idioma.\n\n"
    "Describe esta imagen de una historia de Instagram en UNA sola frase corta "
    "(máximo 15 palabras). Di QUÉ se ve y DÓNDE, por ejemplo: 'selfie en el "
    "gimnasio', 'foto de comida en un restaurante', 'meme sobre política', "
    "'paisaje de playa', 'texto motivacional', 'captura de pantalla de una "
    "conversación'. Sé neutro y objetivo: describe el contenido, nunca el "
    "atractivo de las personas ni uses adjetivos sexuales."
)

# Palabras que delatan otro idioma → se reintenta
_NO_ESPANOL = ("autoportrait", "avec ", "dans ", "une ", "des ", "photo de",
               "le ", "la photo", "portrait", "selbst", "ein ", "mit ")


def disponible(timeout: float = 2.0) -> bool:
    """¿Está el servicio de Ollama levantado?"""
    try:
        urllib.request.urlopen(f"{OLLAMA}/api/tags", timeout=timeout)
        return True
    except Exception:  # noqa: BLE001
        return False


def asegurar_servicio(espera: float = 45.0) -> bool:
    """Arranca Ollama si no está corriendo (para la rutina automática)."""
    import shutil, subprocess, time
    if disponible():
        return True
    binario = None
    for c in ("/Applications/Ollama.app/Contents/Resources/ollama",
              shutil.which("ollama") or ""):
        if c and Path(c).exists():
            binario = c
            break
    if not binario:
        return False
    try:
        subprocess.Popen([binario, "serve"],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True)
    except OSError:
        return False
    fin = time.time() + espera
    while time.time() < fin:
        if disponible(1.0):
            return True
        time.sleep(1.5)
    return False


def modelos() -> list:
    try:
        with urllib.request.urlopen(f"{OLLAMA}/api/tags", timeout=5) as r:
            return [m.get("name", "") for m in json.loads(r.read().decode()).get("models", [])]
    except Exception:  # noqa: BLE001
        return []


def describe(imagen, modelo: str = MODELO) -> str:
    """Describe una imagen. Devuelve '' si no se pudo."""
    ruta = Path(imagen)
    if not ruta.exists():
        return ""
    try:
        datos = base64.b64encode(ruta.read_bytes()).decode("ascii")
    except OSError:
        return ""

    payload = {
        "model": modelo,
        "prompt": PROMPT,
        "images": [datos],
        "stream": False,
        "options": {"temperature": 0.2, "num_predict": 70},
    }
    req = urllib.request.Request(
        f"{OLLAMA}/api/generate",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            texto = json.loads(r.read().decode("utf-8")).get("response", "")
    except Exception:  # noqa: BLE001
        return ""
    texto = " ".join(str(texto).split()).strip().strip('"')

    # Si el modelo contestó en otro idioma, se reintenta una vez
    bajo = texto.lower()
    if any(p in bajo for p in _NO_ESPANOL):
        try:
            payload["prompt"] = "¿Qué se ve en esta imagen? Responde en ESPAÑOL, " \
                                "una sola frase corta y neutra."
            req2 = urllib.request.Request(
                f"{OLLAMA}/api/generate",
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req2, timeout=180) as r2:
                texto = json.loads(r2.read().decode("utf-8")).get("response", texto)
            texto = " ".join(str(texto).split()).strip().strip('"')
        except Exception:  # noqa: BLE001
            pass
    return texto[:200]


def _ffmpeg() -> str:
    import shutil
    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:  # noqa: BLE001
        return ""


def describe_video(video, modelo: str = MODELO) -> str:
    """Extrae un fotograma del video y lo describe (todo local)."""
    ruta = Path(video)
    if not ruta.exists():
        return ""
    exe = _ffmpeg()
    if not exe:
        return ""
    with tempfile.TemporaryDirectory() as tmp:
        frame = Path(tmp) / "frame.jpg"
        for seek in ("1", "0"):
            try:
                subprocess.run(
                    [exe, "-y", "-loglevel", "error", "-ss", seek, "-i", str(ruta),
                     "-frames:v", "1", "-q:v", "3", str(frame)],
                    timeout=60, check=False,
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except Exception:  # noqa: BLE001
                continue
            if frame.exists() and frame.stat().st_size > 0:
                break
        if not frame.exists():
            return ""
        return describe(frame, modelo)


if __name__ == "__main__":
    import sys
    if not disponible():
        raise SystemExit("❌ Ollama no está corriendo. Arranca con:\n"
                         "   /Applications/Ollama.app/Contents/Resources/ollama serve")
    print("modelos:", modelos() or "(ninguno)")
    for arg in sys.argv[1:]:
        fn = describe_video if str(arg).lower().endswith((".mp4", ".mov", ".webm")) else describe
        print(f"{arg} → {fn(arg) or '(no se pudo)'}")
