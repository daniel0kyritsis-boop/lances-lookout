"""Publish the site to a Hugging Face Space (free Docker hosting). No git needed.

One-time setup:
    pip install huggingface_hub
    hf auth login                 # paste a token with "write" access from
                                  # https://huggingface.co/settings/tokens
Then:
    python deploy_hf.py YOUR-USERNAME/lances-lookout

The Space is created if it doesn't exist (public, Docker), then this folder is
uploaded (without .venv, caches, or frames other than the five test targets).
Hugging Face builds the Docker image; the site is live at
https://YOUR-USERNAME-lances-lookout.hf.space a few minutes later.
Run it again after any change to redeploy.
"""
import argparse
from pathlib import Path

ROOT = Path(__file__).parent

# Hugging Face reads Space settings from a YAML block at the top of README.md.
# It's added only to the uploaded copy, so the local README stays clean.
FRONT_MATTER = """---
title: "SPHEREx - Lance's Lookout"
emoji: 🔭
colorFrom: indigo
colorTo: blue
sdk: docker
app_port: 7860
pinned: false
short_description: Blink SPHEREx images to find moving and variable stars
---

"""

TEST_FRAMES = ["barnards-star", "eps-ind-b", "wise-j085510-83-071442-5_d5-6", "rw-aur", "r-dra"]
FAMOUS_FRAMES = ["sirius", "betelgeuse", "vega", "polaris", "rigil-kentaurus", "proxima-centauri",
                 "arcturus", "antares", "rigel", "aldebaran", "mira", "algol", "eta-car",
                 "wolf-359", "61-cyg-a", "trappist-1", "kic-8462852"]
ALLOW = (["server.py", "Dockerfile", ".dockerignore", "requirements.txt", "prefetch.py",
          "make_frames.py", "plot_epochs.py", "build_names.py", "web/*", "spherex_data/*.py",
          "spherex_data/*.json", "tests/*.py"]
         + [f"frames/{name}/*" for name in TEST_FRAMES + FAMOUS_FRAMES])


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("space", help="YOUR-USERNAME/space-name, e.g. jdoe/lances-lookout")
    ap.add_argument("--private", action="store_true", help="make the Space private")
    a = ap.parse_args()

    from huggingface_hub import HfApi

    missing = [n for n in TEST_FRAMES if not (ROOT / "frames" / n / "frames.json").exists()]
    if missing:
        print("Note: no pre-built frames for", ", ".join(missing),
              "- the Space will build them on start-up (slower first load).")

    api = HfApi()
    api.create_repo(a.space, repo_type="space", space_sdk="docker", private=a.private, exist_ok=True)
    api.upload_folder(repo_id=a.space, repo_type="space", folder_path=ROOT, allow_patterns=ALLOW,
                      commit_message="Deploy SPHEREx - Lance's Lookout")
    readme = FRONT_MATTER + (ROOT / "README.md").read_text(encoding="utf-8")
    api.upload_file(repo_id=a.space, repo_type="space", path_or_fileobj=readme.encode("utf-8"),
                    path_in_repo="README.md", commit_message="Update README")
    user, name = a.space.split("/")
    print(f"Uploaded. Build log: https://huggingface.co/spaces/{a.space}")
    print(f"Site (live once the build finishes): https://{user.lower()}-{name.lower()}.hf.space")


if __name__ == "__main__":
    main()
