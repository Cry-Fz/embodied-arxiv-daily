#!/usr/bin/env python3
"""Add Simplified Chinese title/summary fields to generated arXiv paper JSON."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.request
from datetime import date as dt_date
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


DEFAULT_LLM_API_URL = "https://api.openai.com/v1/chat/completions"
LLM_SYSTEM_PROMPT = """
You translate arXiv paper metadata for a Chinese robotics and embodied AI paper archive.
Translate titles and abstracts into natural, concise Simplified Chinese.
Preserve technical terms, model names, dataset names, method names, robot/platform names,
benchmarks, acronyms, formulas, URLs, code identifiers, and arXiv IDs when translating them
would make the result less precise. Keep author names unchanged.
Return JSON only, with this shape:
{"translations":[{"id":"...","title_zh":"...","summary_zh":"..."}]}
""".strip()


def parse_args() -> argparse.Namespace:
  parser = argparse.ArgumentParser(description="Translate generated paper titles and summaries.")
  parser.add_argument("--data-dir", default="data/papers", help="Directory containing daily paper JSON files.")
  parser.add_argument("--date", help="End archive date in YYYY-MM-DD. Defaults to today in --timezone.")
  parser.add_argument("--days", type=int, default=1, help="Translate N days ending at --date.")
  parser.add_argument("--all", action="store_true", help="Translate all local daily files.")
  parser.add_argument("--timezone", default="Asia/Shanghai", help="Timezone used for default --date.")
  parser.add_argument("--provider", choices=["google", "llm"], default=os.environ.get("TRANSLATION_PROVIDER") or "google")
  parser.add_argument("--batch-size", type=int, default=20, help="Number of papers per progress batch.")
  parser.add_argument("--limit", type=int, default=0, help="Maximum papers to translate per file. 0 means no limit.")
  parser.add_argument("--overwrite", action="store_true", help="Overwrite existing title_zh and summary_zh fields.")
  parser.add_argument("--sleep", type=float, default=0.5, help="Seconds to wait between Google Translate requests.")
  parser.add_argument("--batch-sleep", type=float, default=2.0, help="Seconds to wait between Google batches.")
  parser.add_argument("--api-url", default=os.environ.get("TRANSLATION_API_URL") or DEFAULT_LLM_API_URL)
  parser.add_argument("--api-key-env", default="TRANSLATION_API_KEY", help="Environment variable containing LLM API key.")
  parser.add_argument("--model", default=os.environ.get("TRANSLATION_MODEL", ""))
  return parser.parse_args()


def load_json(path: Path) -> dict[str, Any]:
  with path.open("r", encoding="utf-8") as handle:
    return json.load(handle)


def write_json(path: Path, payload: dict[str, Any]) -> None:
  with path.open("w", encoding="utf-8") as handle:
    json.dump(payload, handle, ensure_ascii=False, indent=2)
    handle.write("\n")


def parse_target_date(value: str | None, tz_name: str) -> dt_date:
  if value:
    return dt_date.fromisoformat(value)
  return datetime.now(ZoneInfo(tz_name)).date()


def target_paths(args: argparse.Namespace) -> list[Path]:
  data_dir = Path(args.data_dir)
  if args.all:
    return sorted(data_dir.glob("*.json"))

  if args.days < 1:
    raise ValueError("--days must be >= 1")

  end_date = parse_target_date(args.date, args.timezone)
  start_date = end_date - timedelta(days=args.days - 1)
  paths = []
  current_date = start_date
  while current_date <= end_date:
    path = data_dir / f"{current_date.isoformat()}.json"
    if path.exists():
      paths.append(path)
    current_date += timedelta(days=1)
  return paths


def paper_id(paper: dict[str, Any], fallback: int) -> str:
  return str(paper.get("arxiv_id") or paper.get("abs_url") or paper.get("title") or fallback)


def needs_translation(paper: dict[str, Any], overwrite: bool) -> bool:
  if overwrite:
    return True
  return not paper.get("title_zh") or not paper.get("summary_zh")


def chunked(items: list[dict[str, Any]], size: int) -> list[list[dict[str, Any]]]:
  return [items[index : index + size] for index in range(0, len(items), size)]


def collect_items(papers: list[dict[str, Any]], overwrite: bool, limit: int) -> list[dict[str, Any]]:
  items = []
  for index, paper in enumerate(papers):
    if not needs_translation(paper, overwrite):
      continue
    title = str(paper.get("title", "")).strip()
    summary = str(paper.get("summary", "")).strip()
    if not title or not summary:
      continue
    items.append(
      {
        "id": paper_id(paper, index),
        "paper": paper,
        "title": title,
        "summary": summary,
      }
    )
    if limit and len(items) >= limit:
      break
  return items


def safe_google_translate(translator: Any, text: str, sleep_seconds: float) -> str:
  try:
    translated = translator.translate(text)
    return translated or text
  except Exception as error:
    print(f"Google translation error: {error}", file=sys.stderr)
    return text
  finally:
    time.sleep(max(0, sleep_seconds))


def translate_google_items(items: list[dict[str, Any]], args: argparse.Namespace) -> dict[str, dict[str, str]]:
  try:
    from deep_translator import GoogleTranslator  # noqa: PLC0415
  except ImportError as error:
    raise RuntimeError("Missing dependency: run `pip install -r requirements.txt`.") from error

  translator = GoogleTranslator(source="en", target="zh-CN")
  translations: dict[str, dict[str, str]] = {}
  completed = 0
  batches = chunked(items, max(1, args.batch_size))

  for batch_index, batch in enumerate(batches):
    for item in batch:
      translations[item["id"]] = {
        "title_zh": safe_google_translate(translator, item["title"], args.sleep),
        "summary_zh": safe_google_translate(translator, item["summary"], args.sleep),
      }
      completed += 1
    print(f"  translation progress {completed}/{len(items)}")
    if batch_index + 1 < len(batches):
      time.sleep(max(0, args.batch_sleep))

  return translations


def extract_json_object(text: str) -> dict[str, Any]:
  cleaned = text.strip()
  fence_match = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", cleaned, flags=re.DOTALL | re.IGNORECASE)
  if fence_match:
    cleaned = fence_match.group(1).strip()
  if not cleaned.startswith("{"):
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start >= 0 and end > start:
      cleaned = cleaned[start : end + 1]
  return json.loads(cleaned)


def translate_llm_batch(
  batch: list[dict[str, Any]],
  api_url: str,
  api_key: str,
  model: str,
) -> dict[str, dict[str, str]]:
  payload = {
    "papers": [
      {
        "id": item["id"],
        "title": item["title"],
        "summary": item["summary"],
      }
      for item in batch
    ]
  }
  body = {
    "model": model,
    "messages": [
      {"role": "system", "content": LLM_SYSTEM_PROMPT},
      {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
    ],
    "temperature": 0,
  }
  request = urllib.request.Request(
    api_url,
    data=json.dumps(body).encode("utf-8"),
    headers={
      "Authorization": f"Bearer {api_key}",
      "Content-Type": "application/json",
    },
  )
  with urllib.request.urlopen(request, timeout=180) as response:
    result = json.loads(response.read().decode("utf-8"))

  content = result["choices"][0]["message"]["content"]
  parsed = extract_json_object(content)
  translations = parsed.get("translations", [])
  return {
    str(item.get("id")): {
      "title_zh": str(item.get("title_zh", "")).strip(),
      "summary_zh": str(item.get("summary_zh", "")).strip(),
    }
    for item in translations
    if item.get("id")
  }


def translate_llm_items(items: list[dict[str, Any]], args: argparse.Namespace) -> dict[str, dict[str, str]]:
  api_key = os.environ.get(args.api_key_env, "")
  if not api_key:
    raise RuntimeError(f"Missing translation API key env var: {args.api_key_env}")
  if not args.model:
    raise RuntimeError("Missing translation model. Set TRANSLATION_MODEL or pass --model.")

  translations: dict[str, dict[str, str]] = {}
  completed = 0
  for batch in chunked(items, max(1, args.batch_size)):
    translations.update(translate_llm_batch(batch, args.api_url, api_key, args.model))
    completed += len(batch)
    print(f"  translation progress {completed}/{len(items)}")
  return translations


def translate_items(items: list[dict[str, Any]], args: argparse.Namespace) -> dict[str, dict[str, str]]:
  if args.provider == "llm":
    return translate_llm_items(items, args)
  return translate_google_items(items, args)


def translate_file(path: Path, args: argparse.Namespace) -> int:
  payload = load_json(path)
  papers = payload.get("papers", [])
  if not isinstance(papers, list):
    return 0

  items = collect_items(papers, args.overwrite, args.limit)
  if not items:
    return 0

  translations = translate_items(items, args)
  generated_at = datetime.now(timezone.utc).isoformat()
  translated_count = 0

  for item in items:
    translated = translations.get(item["id"])
    if not translated:
      print(f"{path}: missing translation for {item['id']}", file=sys.stderr)
      continue
    item["paper"]["title_zh"] = translated["title_zh"] or item["paper"].get("title_zh", "") or item["paper"].get("title", "")
    item["paper"]["summary_zh"] = (
      translated["summary_zh"] or item["paper"].get("summary_zh", "") or item["paper"].get("summary", "")
    )
    item["paper"]["translation"] = {
      "language": "zh-CN",
      "provider": args.provider,
      "model": args.model if args.provider == "llm" else "deep-translator/google",
      "generated_at": generated_at,
    }
    translated_count += 1

  if translated_count:
    write_json(path, payload)
  return translated_count


def main() -> int:
  args = parse_args()
  total = 0
  paths = target_paths(args)
  for path in paths:
    count = translate_file(path, args)
    total += count
    print(f"{path}: translated {count} papers.")

  print(f"Translated {total} papers across {len(paths)} files with provider={args.provider}.")
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
