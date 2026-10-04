"""`harness architect --from-explore`: frozen cards -> ADRs + decision rows.

Each chosen card becomes one ADR in `adr/`. The ADR front matter carries
one decision row (answer of 150 words or fewer). The ADR body carries the
full card. Parked cards become deferred open questions in the working
document. Architect never asks again a question that a card answers.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

from engine import HarnessError
from engine.explore import (EXPLORE_DIR, body_digest, chosen_letter,
                            chosen_option, explore_path, freeze_state,
                            front_matter, parse_cards, parse_open,
                            validate_cards)

MAX_ANSWER_WORDS = 150
DEFAULT_DOMAIN = "architecture"
SEED_HEADER = "# Architecture — seeded from explore/DECISIONS.md"
_NUMBERED = re.compile(r"^(\d+)")


def _sentence(text: str) -> str:
    text = text.strip()
    return text if not text or text[-1] in ".!?" else text + "."


def _slug(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:50].rstrip("-") or "decision"


def card_domain(card: dict) -> str:
    """The row domain: the card's `Domain` field, or `architecture`."""
    value = card["fields"].get("Domain", "").strip()
    if not value or (value.startswith("<") and value.endswith(">")):
        return DEFAULT_DOMAIN
    return re.sub(r"\s+", "-", value.lower())


def row_answer(card: dict, adr_ref: str) -> str:
    """The decision-row answer for a chosen card.

    Raises:
        HarnessError: The answer is over 150 words.
    """
    opt = chosen_option(card)
    f = opt["fields"]
    answer = " ".join([
        _sentence(opt["name"]), _sentence(f["Solves"]),
        "Trade-off: " + _sentence(f["Trade-off"]),
        "Undo cost: " + _sentence(f["Undo cost"]),
        f"Full card: {adr_ref}."])
    words = len(answer.split())
    if words > MAX_ANSWER_WORDS:
        raise HarnessError(
            f"{card['id']}: the decision row has {words} words; the limit is "
            f"{MAX_ANSWER_WORDS}. Shorten the chosen option's fields, then "
            f"freeze again.")
    return answer


def _status(state: dict) -> str:
    return ("Accepted. The human froze this card in `explore/DECISIONS.md`.\n"
            f"Frozen by: {state['frozen_by']}. Commit: "
            f"{state['frozen_at_commit']}.")


_STATUS = re.compile(r"## Status\n\n(.*?)\n\n## Decision card", re.S)


def _demote(markdown: str) -> str:
    """`## x` -> `### x`, `### x` -> `#### x`, so the card nests in the ADR."""
    return re.sub(r"^(#{2,5})(\s)", r"#\1\2", markdown, flags=re.M)


def render_adr(adr_id: str, card: dict, adr_ref: str, state: dict,
               status_block: str | None = None) -> str:
    """The full ADR text for one chosen card.

    `status_block` keeps an existing ADR's Status text, so a re-freeze at a
    new commit does not make an unchanged card look changed.
    """
    import yaml
    domain = card_domain(card)
    front = {
        "id": adr_id, "status": "accepted", "domains": [domain],
        "supersedes": [], "explore_card": card["id"],
        "decision_table_rows": [{
            "id": card["id"], "domain": domain,
            "question": card["question"],
            "answer": row_answer(card, adr_ref)}],
        "abstractions": [],
    }
    head = yaml.safe_dump(front, sort_keys=False, allow_unicode=True,
                          width=1000).rstrip("\n")
    return "\n".join([
        "---", head, "---", "",
        f"# ADR-{adr_id}: {card['question']}", "",
        "## Status", "",
        status_block if status_block is not None else _status(state), "",
        "## Decision card", "",
        _demote(card["raw"]), ""])


def _explore_adrs(root: Path) -> dict[str, tuple[Path, str]]:
    """Map card id -> (ADR path, ADR id) for in-force explore ADRs.

    Superseded ADRs are skipped: a changed card then gets a new ADR.

    Raises:
        HarnessError: Two in-force ADRs claim the same card.
    """
    from engine.compiler import out_of_force
    gone = out_of_force(root)
    out: dict[str, tuple[Path, str]] = {}
    adr_dir = root / "adr"
    if not adr_dir.is_dir():
        return out
    for path in sorted(adr_dir.glob("*.md")):
        if not _NUMBERED.match(path.name):
            continue
        data, _ = front_matter(path.read_text(encoding="utf-8"))
        card_id = data.get("explore_card")
        if not card_id or str(data.get("id", "")) in gone \
                or str(data.get("status", "")).lower() == "superseded":
            continue
        if str(card_id) in out:
            raise HarnessError(
                f"architect: {out[str(card_id)][0].name} and {path.name} "
                f"both claim card {card_id}. Supersede one of them.")
        out[str(card_id)] = (path, str(data.get("id", "")))
    return out


def _next_number(root: Path) -> int:
    adr_dir = root / "adr"
    paths = adr_dir.glob("*.md") if adr_dir.is_dir() else []
    nums = [int(m.group(1)) for p in paths
            if (m := _NUMBERED.match(p.name))]
    return max(nums, default=0) + 1


def _card_block(card: dict, adr_refs: dict[str, str],
                opens: dict[str, dict]) -> list[str]:
    """The typed block lines for one card: chosen -> `[constraint]`,
    parked -> `[open-question]`."""
    if chosen_letter(card) != "parked":
        opt = chosen_option(card)
        return [f"[constraint] {card['id']}: {card['question']}",
                f"Decided: {_sentence(opt['name'])} Card and reason: "
                f"{adr_refs[card['id']]}. Do not ask this again.", ""]
    entry = opens.get(card["id"])
    if entry and entry["owner"] and entry["trigger"]:
        return [f"[open-question] {card['id']}: {card['question']} "
                f"deferred: {entry['owner']} (trigger: "
                f"{entry['trigger']})", ""]
    return [f"[open-question] {card['id']}: {card['question']} "
            f"(parked; explore/OPEN.md names no owner)", ""]


def _ordered(cards: list[dict]) -> list[dict]:
    """Chosen cards first, then parked cards, each in file order."""
    return ([c for c in cards if chosen_letter(c) != "parked"]
            + [c for c in cards if chosen_letter(c) == "parked"])


def render_doc(cards: list[dict], adr_refs: dict[str, str],
               opens: dict[str, dict]) -> str:
    """The stage-3 working document seeded from the cards."""
    from engine.docsections import DECISIONS_TABLE_HEADER
    out = [SEED_HEADER, "", "<!-- stage: 3 -->", ""]
    for card in _ordered(cards):
        out += _card_block(card, adr_refs, opens)
    out += ["```harness-decisions", *DECISIONS_TABLE_HEADER, "```", ""]
    return "\n".join(out)


def _has_block(text: str, card_id: str) -> bool:
    return re.search(r"\[(?:constraint|open-question)\]\s+"
                     + re.escape(card_id) + r"\s*:", text) is not None


def append_cards(text: str, cards: list[dict], adr_refs: dict[str, str],
                 opens: dict[str, dict]) -> tuple[str, list[str]]:
    """Adds the blocks of cards that the document does not hold yet.

    Args:
        text: The existing working document. Its content and stage marker
            stay as they are.
        cards: The frozen cards.
        adr_refs: Card id -> ADR path, for chosen cards.
        opens: Parked questions from `explore/OPEN.md`.

    Returns:
        (new text, appended card ids). A card id that already has a
        `[constraint]` or `[open-question]` block is skipped.
    """
    added: list[str] = []
    lines: list[str] = []
    for card in _ordered(cards):
        if _has_block(text, card["id"]):
            continue
        lines += _card_block(card, adr_refs, opens)
        added.append(card["id"])
    if not added:
        return text, []
    head = text if text.endswith("\n") or not text else text + "\n"
    sep = "" if not head or head.endswith("\n\n") else "\n"
    return head + sep + "\n".join(lines), added


def relink_cards(text: str, cards: list[dict],
                 adr_refs: dict[str, str]) -> tuple[str, list[str]]:
    """Points seeded `Decided:` lines at each chosen card's current ADR.

    Only the `Decided: ... Card and reason: adr/....md. Do not ask this
    again.` line that the seed writes right under `[constraint] <id>:` is
    rewritten, and only when it cites another ADR. Other text stays.

    Returns:
        (new text, relinked card ids).
    """
    relinked: list[str] = []
    for card in cards:
        ref = adr_refs.get(card["id"])
        if ref is None:
            continue
        pattern = re.compile(
            r"(^\[constraint\]\s+" + re.escape(card["id"]) + r"\s*:[^\n]*\n)"
            r"Decided: [^\n]*? Card and reason: (adr/[^\s]+?\.md)\. "
            r"Do not ask this again\.$", re.M)
        found = pattern.search(text)
        if found is None or found.group(2) == ref:
            continue
        line = _card_block(card, adr_refs, {})[1]
        text = text[:found.start()] + found.group(1) + line \
            + text[found.end():]
        relinked.append(card["id"])
    return text, relinked


_STAGE = re.compile(r"<!-- stage: (\d+) -->")


def seed_from_explore(root, doc: Path, force: bool = False) -> dict:
    """Writes ADRs and the working document from frozen decision cards.

    Args:
        root: Repo root.
        doc: The working document to write.
        force: Reseed the working document from scratch. It never
            rewrites an ADR that already exists.

    Returns:
        `{"doc", "stage", "adrs", "unchanged", "rows", "parked", "stale",
        "appended", "relinked", "source"}`. Without `force`, an existing
        document keeps its content and stage; `appended` lists the card ids
        whose blocks were added to it, and `relinked` the cards whose
        seeded `Decided:` line now cites a new ADR. `stale` lists explore ADRs whose card is no
        longer chosen; they are kept, because accepted ADRs are immutable.

    Raises:
        HarnessError: explore/ is not frozen, a card is not valid, the
            cards changed after freeze, two ADRs claim one card, or an
            explore ADR in force differs from its card. Nothing is written
            then.
    """
    root = Path(root)
    state = freeze_state(root)
    if state is None:
        raise HarnessError("architect: explore/DECISIONS.md is not frozen. "
                           "Run: harness explore --freeze")
    text = explore_path(root, "DECISIONS.md").read_text(encoding="utf-8")
    cards = parse_cards(text)
    problems = validate_cards(cards)
    if problems:
        more = (f" ...and {len(problems) - 1} more." if len(problems) > 1
                else "")
        raise HarnessError(
            f"architect: explore/DECISIONS.md is not valid. "
            f"{problems[0]}{more} Run: harness explore --freeze to list them")
    if front_matter(text)[0].get("frozen_digest") != body_digest(text):
        raise HarnessError("architect: explore/DECISIONS.md changed after "
                           "freeze. Run: harness explore --freeze")
    existing = _explore_adrs(root)
    number = _next_number(root)
    bodies: dict[str, tuple[Path, str, str]] = {}
    for card in cards:
        if chosen_letter(card) == "parked":
            continue
        if card["id"] in existing:
            path, adr_id = existing[card["id"]]
        else:
            adr_id = f"{number:03d}"
            path = root / "adr" / f"{adr_id}-{_slug(card['question'])}.md"
            number += 1
        ref = f"adr/{path.name}"
        body = render_adr(adr_id, card, ref, state)
        if path.exists():
            found = _STATUS.search(path.read_text(encoding="utf-8"))
            if found:
                kept = render_adr(adr_id, card, ref, state, found.group(1))
                if kept == path.read_text(encoding="utf-8"):
                    body = kept
        bodies[card["id"]] = (path, ref, body)
    for cid, (path, ref, body) in bodies.items():
        if not path.exists() or path.read_text(encoding="utf-8") == body:
            continue
        status = str(front_matter(path.read_text(encoding="utf-8"))[0]
                     .get("status", "")).lower()
        if status != "accepted":
            raise HarnessError(
                f"architect: {ref} has status {status!r} and its card "
                f"changed. Set it to accepted or supersede it with a new "
                f"ADR.")
        raise HarnessError(
            f"architect: {ref} records a different choice for {cid}. Write "
            f"an ADR that supersedes it, then run this again.")
    open_path = explore_path(root, "OPEN.md")
    opens = (parse_open(open_path.read_text(encoding="utf-8"))
             if open_path.is_file() else {})
    refs = {cid: ref for cid, (_path, ref, _body) in bodies.items()}
    old_doc = (doc.read_text(encoding="utf-8")
               if doc.exists() and not force else None)
    written, unchanged = [], []
    (root / "adr").mkdir(exist_ok=True)
    for path, ref, body in bodies.values():
        if path.exists():
            unchanged.append(ref)
            continue
        path.write_text(body, encoding="utf-8")
        written.append(ref)
    if old_doc is None:
        doc.parent.mkdir(parents=True, exist_ok=True)
        doc.write_text(render_doc(cards, refs, opens), encoding="utf-8")
        stage, appended = 3, [c["id"] for c in _ordered(cards)]
        relinked: list[str] = []
    else:
        new_doc, relinked = relink_cards(old_doc, cards, refs)
        new_doc, appended = append_cards(new_doc, cards, refs, opens)
        if new_doc != old_doc:
            doc.write_text(new_doc, encoding="utf-8")
        marker = _STAGE.search(old_doc)
        stage = int(marker.group(1)) if marker else 1
    stale = sorted(f"adr/{p.name}" for cid, (p, _i)
                   in existing.items() if cid not in bodies)
    for ref in stale:
        print(f"check: {ref} is accepted but its card is parked or gone. "
              f"Write an ADR that supersedes {ref}.", file=sys.stderr)
    return {"doc": str(doc), "stage": stage, "adrs": written,
            "unchanged": unchanged, "rows": sorted(bodies),
            "parked": [c["id"] for c in cards
                       if chosen_letter(c) == "parked"],
            "stale": stale, "appended": appended, "relinked": relinked,
            "source": f"{EXPLORE_DIR}/DECISIONS.md"}
