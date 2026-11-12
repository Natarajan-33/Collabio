"""Set the Render services' environment from the local .env files, via the Render API.

Usage (from backend/):
  uv run python -m scripts.render_env status            # service ids, URLs, latest deploys
  uv run python -m scripts.render_env push [--deploy]   # set env vars (names printed, never values)
  uv run python -m scripts.render_env set KEY=VALUE [--service collabio-api] [--deploy]

Reads RENDER_API_KEY from the environment or backend/.env. Values come from backend/.env (API)
and frontend/.env.local (web); the public URLs are taken from the services themselves, so a
Render name suffix is handled. Nothing secret is printed.
"""

import os
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[2]
API = "https://api.render.com/v1"

# Everything in the local .env files is pushed, except what Render itself owns or must differ
# from local development (public URLs, the generated internal secret, mode flags, test-only ids).
API_SKIP = {
    "PUBLIC_BACKEND_URL",
    "PUBLIC_FRONTEND_URL",
    "FRONTEND_ORIGIN",
    "FRONTEND_ORIGIN_REGEX",
    "WORKERS_ENABLED",
    "HACKATHON_MODE",
    "INTERNAL_SECRET",
    "PAYPAL_TEST_CAPTURE_ID",
    "RENDER_WORKFLOWS_ENABLED",
}
WEB_SKIP = {"NEXT_PUBLIC_API_URL", "NEXT_PUBLIC_HACKATHON_MODE"}


def read_env(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    if not path.exists():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def client() -> httpx.Client:
    key = os.environ.get("RENDER_API_KEY") or read_env(ROOT / "backend/.env").get("RENDER_API_KEY")
    if not key:
        sys.exit("RENDER_API_KEY is not set (environment or backend/.env)")
    return httpx.Client(base_url=API, headers={"Authorization": f"Bearer {key}"}, timeout=30)


def services(c: httpx.Client) -> dict[str, dict]:
    r = c.get("/services", params={"limit": 100})
    r.raise_for_status()
    found = {}
    for row in r.json():
        s = row["service"]
        if s["name"].startswith("collabio-"):
            found[s["name"]] = s
    return found


def url_of(s: dict) -> str:
    return (s.get("serviceDetails") or {}).get("url", "")


def put(c: httpx.Client, service_id: str, key: str, value: str) -> None:
    r = c.put(f"/services/{service_id}/env-vars/{key}", json={"value": value})
    r.raise_for_status()


def deploy(c: httpx.Client, service_id: str) -> str:
    r = c.post(f"/services/{service_id}/deploys", json={"clearCache": "do_not_clear"})
    r.raise_for_status()
    return r.json().get("id", "?")


def status() -> None:
    with client() as c:
        for name, s in sorted(services(c).items()):
            r = c.get(f"/services/{s['id']}/deploys", params={"limit": 1})
            last = r.json()[0]["deploy"] if r.status_code == 200 and r.json() else {}
            print(
                f"{name}: id={s['id']} url={url_of(s) or '-'} "
                f"branch={s.get('branch')} last_deploy={last.get('status', '-')}"
            )


def push(do_deploy: bool) -> None:
    backend = read_env(ROOT / "backend/.env")
    frontend = read_env(ROOT / "frontend/.env.local")
    with client() as c:
        svc = services(c)
        api, web = svc.get("collabio-api"), svc.get("collabio-web")
        if not api or not web:
            sys.exit(f"missing services; found: {sorted(svc)}")
        api_url, web_url = url_of(api), url_of(web)
        plan = {
            api["id"]: {k: v for k, v in backend.items() if v and k not in API_SKIP}
            | {
                "FRONTEND_ORIGIN": web_url,
                "PUBLIC_FRONTEND_URL": web_url,
                "PUBLIC_BACKEND_URL": api_url,
            },
            web["id"]: {k: v for k, v in frontend.items() if v and k not in WEB_SKIP}
            | {"NEXT_PUBLIC_API_URL": api_url},
        }
        cron = svc.get("collabio-nightly")
        if cron:
            plan[cron["id"]] = {"API_URL": api_url}
        names = {s["id"]: n for n, s in svc.items()}
        for sid, values in plan.items():
            for k, v in values.items():
                put(c, sid, k, v)
            print(f"{names[sid]}: set {', '.join(sorted(values))}")
        if do_deploy:
            for sid in (api["id"], web["id"]):
                print(f"deploy {names[sid]}: {deploy(c, sid)}")


def set_one(arg: str, service: str, do_deploy: bool) -> None:
    key, value = arg.split("=", 1)
    with client() as c:
        s = services(c)[service]
        put(c, s["id"], key, value)
        print(f"{service}: set {key}")
        if do_deploy:
            print(f"deploy {service}: {deploy(c, s['id'])}")


if __name__ == "__main__":
    args = sys.argv[1:]
    flag = "--deploy" in args
    if not args or args[0] not in {"status", "push", "set"}:
        sys.exit(__doc__)
    if args[0] == "status":
        status()
    elif args[0] == "push":
        push(flag)
    else:
        service = args[args.index("--service") + 1] if "--service" in args else "collabio-api"
        set_one(args[1], service, flag)
