"""Automatische Tags (0.20) unter Einstellungen → Tags organisieren → Automatisch taggen.

Logik in services/autotag.py. Regeln gelten fuer alle Mitglieder (wie Tags).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from ..models import RULE_MATCH, Person, Tag, TagRule, User
from ..security import get_db, require_user
from ..services import autotag
from ..services import posts as post_service
from ..templating import redirect, render

router = APIRouter(prefix="/settings/tags/regeln", dependencies=[Depends(require_user)])


def _persons(db: Session) -> list[Person]:
    return list(db.scalars(select(Person).order_by(func.lower(Person.name))))


def _rule(db: Session, rule_id: int) -> TagRule:
    rule = db.get(TagRule, rule_id)
    if rule is None:
        raise HTTPException(status_code=404)
    return rule


def _page(request: Request, db: Session, editing: TagRule | None = None, error: str = "", form: dict | None = None,
          status_code: int = 200):
    rules = list(db.scalars(select(TagRule).options(selectinload(TagRule.tag), selectinload(TagRule.person))
                            .join(Tag, Tag.id == TagRule.tag_id).order_by(TagRule.active.desc(), Tag.name)))
    stats = {}
    for r in rules:
        pv = autotag.preview(db, autotag.matcher_for(r), r.tag_id, r.person_id, limit=0)
        stats[r.id] = pv
    if form is None and editing is not None:
        form = dict(tag=editing.tag.name, terms="\n".join(editing.term_list), match=editing.match,
                    exclude="\n".join(editing.exclude_list), person=editing.person_id or "")
    untagged, reach = autotag.untagged_reach(db) if rules else (0, 0)
    return render(request, "settings/tag_rules.html", section="tags", rules=rules, stats=stats,
                  untagged=untagged, reach=reach,
                  assigned=autotag.assigned_count(db), editing=editing, error=error, form=form or {},
                  persons=_persons(db), all_tags=list(db.scalars(select(Tag.name).order_by(Tag.name))),
                  match_labels=RULE_MATCH, status_code=status_code)


@router.get("")
def rules(request: Request, db: Session = Depends(get_db)):
    return _page(request, db)


@router.get("/vorschau")
def preview(request: Request, tag: str = "", terms: str = "", match: str = "any", exclude: str = "", person: str = "",
            db: Session = Depends(get_db)):
    """htmx: was wuerde die Regel treffen? (waehrend man tippt)"""
    words = autotag.parse_terms(terms)
    name = post_service.normalize_tag(tag)
    tag_obj = db.scalar(select(Tag).where(Tag.name == name)) if name else None
    pv = None
    if words:
        m = autotag.Matcher(words, match if match in RULE_MATCH else "any", autotag.parse_terms(exclude))
        pv = autotag.preview(db, m, tag_obj.id if tag_obj else None, int(person) if person.isdigit() else None)
    return render(request, "partials/tag_rule_preview.html", pv=pv, tag_name=name, tag_exists=tag_obj is not None)


@router.get("/woerter")
def words(request: Request, tag: str = "", person: str = "", db: Session = Depends(get_db)):
    """htmx: Woerter, die in Postings mit diesem Tag oft vorkommen."""
    name = post_service.normalize_tag(tag)
    tag_obj = db.scalar(select(Tag).where(Tag.name == name)) if name else None
    hints = autotag.word_hints(db, tag_obj, int(person) if person.isdigit() else None) if tag_obj else []
    return render(request, "partials/tag_rule_words.html", hints=hints, tag_name=name, tag_exists=tag_obj is not None)


def _save(db: Session, rule: TagRule, tag: str, terms: str, match: str, exclude: str, person: str) -> str:
    name = post_service.normalize_tag(tag)
    if not name:
        return "Bitte ein Tag angeben."
    words = autotag.parse_terms(terms)
    if not words:
        return "Bitte mindestens einen Begriff angeben."
    rule.tag = post_service.get_or_create_tags(db, [name])[0]
    rule.terms = "\n".join(words)
    rule.match = match if match in RULE_MATCH else "any"
    rule.exclude = "\n".join(autotag.parse_terms(exclude))
    rule.person_id = int(person) if person.isdigit() and db.get(Person, int(person)) else None
    return ""


@router.post("")
def create(request: Request, tag: str = Form(""), terms: str = Form(""), match: str = Form("any"),
           exclude: str = Form(""), person: str = Form(""), user: User = Depends(require_user),
           db: Session = Depends(get_db)):
    rule = TagRule(created_by_id=user.id)
    error = _save(db, rule, tag, terms, match, exclude, person)
    if error:
        db.rollback()
        return _page(request, db, error=error, form=dict(tag=tag, terms=terms, match=match, exclude=exclude, person=person),
                     status_code=400)
    db.add(rule)
    db.commit()
    return redirect(request, f"/settings/tags/regeln#regel-{rule.id}",
                    toast=f"Regel für #{rule.tag.name} gespeichert – gilt ab jetzt für neue Postings")


@router.post("/alle-anwenden")
def apply_all(request: Request, db: Session = Depends(get_db)):
    """Alle aktiven Regeln auf Postings ohne Tag (rueckgaengig je Regel moeglich)."""
    posts, tags = autotag.apply_all_untagged(db)
    db.commit()
    msg = f"{posts} {'Posting' if posts == 1 else 'Postings'} ohne Tag getaggt ({tags} Tags)" if posts else "Keine ungetaggten Postings passend"
    return redirect(request, "/settings/tags/regeln", toast=msg)


@router.get("/{rule_id}")
def edit_form(request: Request, rule_id: int, db: Session = Depends(get_db)):
    return _page(request, db, editing=_rule(db, rule_id))


@router.post("/{rule_id}")
def update(request: Request, rule_id: int, tag: str = Form(""), terms: str = Form(""), match: str = Form("any"),
           exclude: str = Form(""), person: str = Form(""), db: Session = Depends(get_db)):
    rule = _rule(db, rule_id)
    error = _save(db, rule, tag, terms, match, exclude, person)
    if error:
        db.rollback()
        return _page(request, db, editing=_rule(db, rule_id), error=error, status_code=400,
                     form=dict(tag=tag, terms=terms, match=match, exclude=exclude, person=person))
    db.commit()
    return redirect(request, f"/settings/tags/regeln#regel-{rule.id}", toast=f"Regel für #{rule.tag.name} gespeichert")


@router.post("/{rule_id}/aktiv")
def toggle(request: Request, rule_id: int, db: Session = Depends(get_db)):
    rule = _rule(db, rule_id)
    rule.active = not rule.active
    db.commit()
    return redirect(request, f"/settings/tags/regeln#regel-{rule.id}",
                    toast=f"Regel für #{rule.tag.name} {'aktiv' if rule.active else 'pausiert'}")


@router.get("/{rule_id}/anwenden")
def apply_form(request: Request, rule_id: int, db: Session = Depends(get_db)):
    rule = _rule(db, rule_id)
    pv = autotag.preview(db, autotag.matcher_for(rule), rule.tag_id, rule.person_id, limit=30)
    return render(request, "settings/tag_rule_apply.html", section="tags", rule=rule, pv=pv)


@router.post("/{rule_id}/anwenden")
def apply(request: Request, rule_id: int, scope: str = Form("untagged"), db: Session = Depends(get_db)):
    rule = _rule(db, rule_id)
    n = autotag.apply_to_existing(db, rule, only_untagged=scope != "all")
    db.commit()
    msg = f"#{rule.tag.name} an {n} {'Posting' if n == 1 else 'Postings'} vergeben" if n else "Keine weiteren Postings passend"
    return redirect(request, f"/settings/tags/regeln#regel-{rule.id}", toast=msg)


@router.post("/{rule_id}/rueckgaengig")
def undo(request: Request, rule_id: int, db: Session = Depends(get_db)):
    rule = _rule(db, rule_id)
    n = autotag.undo(db, rule)
    db.commit()
    post_service.remove_orphan_tags(db)
    db.commit()
    return redirect(request, f"/settings/tags/regeln#regel-{rule.id}",
                    toast=f"#{rule.tag.name} von {n} {'Posting' if n == 1 else 'Postings'} wieder entfernt")


@router.post("/{rule_id}/loeschen")
def remove(request: Request, rule_id: int, db: Session = Depends(get_db)):
    rule = _rule(db, rule_id)
    name = rule.tag.name
    db.delete(rule)  # vergebene Tags bleiben; auto_tags.rule_id wird NULL
    db.commit()
    post_service.remove_orphan_tags(db)
    db.commit()
    return redirect(request, "/settings/tags/regeln", toast=f"Regel für #{name} gelöscht – vergebene Tags bleiben")
