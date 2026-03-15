from typing import List, Optional, Union
import logging
import json

import anyio
from fastapi import APIRouter, Depends, Form, Request, UploadFile, File, Query
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session
from sqlalchemy import select, func, or_, text as sql_text

from app.db import get_db
from app.models import Question, Answer, Admin
from app.security import (
    hash_password,
    verify_password,
    password_length_ok,
    sessions,
    SessionData,
    now_ts,
    get_cookie_name,
)
from app.deps import require_login, require_role, require_csrf
from app.validators import (
    validate_question_text,
    validate_answer_text,
    parse_tags,
)
from app.embeddings import encode_question_embedding
from app.media import save_images, delete_media_files
from app.config import settings
from app.web.templating import templates

log = logging.getLogger("kb_admin")
router = APIRouter()


def _base_path() -> str:
    return (settings.root_path or "").rstrip("/")


def _u(path: str) -> str:
    if not path.startswith("/"):
        path = "/" + path
    return f"{_base_path()}{path}"


def _redirect(path: str) -> RedirectResponse:
    return RedirectResponse(url=_u(path), status_code=303)


def clamp(n: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, n))


def _get_single_answer(db: Session, question_id: int) -> Optional[Answer]:
    return db.scalar(select(Answer).where(Answer.question_id == question_id).order_by(Answer.id.asc()).limit(1))


async def _embed_with_timeout(text: str, seconds: int = 30):
    with anyio.fail_after(seconds):
        return await anyio.to_thread.run_sync(encode_question_embedding, text)


def _emb_to_json_str(emb: Optional[List[float]]) -> Optional[str]:
    if emb is None:
        return None
    return json.dumps(emb, ensure_ascii=False, separators=(",", ":"))


def _insert_question_with_vector(db: Session, text_val: str, tags_val: Optional[str], emb: Optional[List[float]]) -> int:
    emb_json = _emb_to_json_str(emb)
    if emb_json is None:
        stmt = sql_text("INSERT INTO questions (text, tags) VALUES (:text, :tags)")
        db.execute(stmt, {"text": text_val, "tags": tags_val})
    else:
        stmt = sql_text("INSERT INTO questions (text, embedding, tags) VALUES (:text, VEC_FromText(:emb_json), :tags)")
        db.execute(stmt, {"text": text_val, "emb_json": emb_json, "tags": tags_val})

    new_id = db.execute(sql_text("SELECT LAST_INSERT_ID()")).scalar_one()
    return int(new_id)


def _update_question_with_vector(db: Session, qid: int, text_val: str, tags_val: Optional[str], emb: Optional[List[float]]):
    emb_json = _emb_to_json_str(emb)
    if emb_json is None:
        stmt = sql_text("UPDATE questions SET text=:text, tags=:tags, embedding=NULL WHERE id=:id")
        db.execute(stmt, {"id": qid, "text": text_val, "tags": tags_val})
    else:
        stmt = sql_text("UPDATE questions SET text=:text, tags=:tags, embedding=VEC_FromText(:emb_json) WHERE id=:id")
        db.execute(stmt, {"id": qid, "text": text_val, "tags": tags_val, "emb_json": emb_json})


def _normalize_files(files: Union[UploadFile, List[UploadFile], None]) -> List[UploadFile]:
    if files is None:
        return []
    if isinstance(files, list):
        lst = files
    else:
        lst = [files]
    out: List[UploadFile] = []
    for f in lst:
        if not f:
            continue
        if not getattr(f, "filename", ""):
            continue
        out.append(f)
    return out


@router.get("/", response_class=HTMLResponse)
def home(request: Request):
    require_login(request)
    return _redirect("/questions")


@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request, db: Session = Depends(get_db), next: str = Query(default="")):
    admins_count = db.scalar(select(func.count()).select_from(Admin)) or 0
    next_url = next.strip() if next else _u("/questions")
    return templates.TemplateResponse("login.html", {"request": request, "admins_count": admins_count, "next": next_url})


@router.post("/login")
def login_action(
    request: Request,
    login: str = Form(...),
    password: str = Form(...),
    next: str = Form(""),
    db: Session = Depends(get_db),
):
    login = (login or "").strip()
    admin = db.scalar(select(Admin).where(Admin.username == login))
    if not admin or not verify_password(password, admin.password_hash):
        admins_count = db.scalar(select(func.count()).select_from(Admin)) or 0
        return templates.TemplateResponse(
            "login.html",
            {"request": request, "error": "Неверный логин или пароль.", "admins_count": admins_count, "next": next or _u("/questions")},
            status_code=400,
        )

    token = sessions.create(SessionData(admin_id=admin.id, username=admin.username, role=admin.role, issued_at=now_ts()))
    resp = RedirectResponse(url=(next or _u("/questions")), status_code=303)
    resp.set_cookie(
        key=get_cookie_name(),
        value=token,
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
        max_age=60 * 60 * 12,
    )
    return resp


@router.post("/logout")
def logout_action(request: Request):
    token = request.cookies.get(get_cookie_name(), "")
    if token:
        sessions.delete(token)
    resp = _redirect("/login")
    resp.delete_cookie(get_cookie_name())
    return resp


@router.get("/setup", response_class=HTMLResponse)
def setup_page(request: Request, db: Session = Depends(get_db)):
    admins_count = db.scalar(select(func.count()).select_from(Admin)) or 0
    if admins_count > 0:
        return _redirect("/login")
    return templates.TemplateResponse("setup_first_admin.html", {"request": request})


@router.post("/setup")
def setup_action(
    request: Request,
    login: str = Form(...),
    password: str = Form(...),
    password2: str = Form(...),
    db: Session = Depends(get_db),
):
    admins_count = db.scalar(select(func.count()).select_from(Admin)) or 0
    if admins_count > 0:
        return _redirect("/login")

    login = (login or "").strip()
    if not login or len(login) > 50:
        return templates.TemplateResponse("setup_first_admin.html", {"request": request, "error": "Некорректный логин."}, status_code=400)

    if password != password2:
        return templates.TemplateResponse("setup_first_admin.html", {"request": request, "error": "Пароли не совпадают."}, status_code=400)

    ok, err = password_length_ok(password)
    if not ok:
        return templates.TemplateResponse("setup_first_admin.html", {"request": request, "error": err}, status_code=400)

    exists = db.scalar(select(Admin).where(Admin.username == login))
    if exists:
        return templates.TemplateResponse("setup_first_admin.html", {"request": request, "error": "Такой логин уже существует."}, status_code=400)

    admin = Admin(username=login, password_hash=hash_password(password), role="admin")
    db.add(admin)
    db.commit()
    return _redirect("/login")


@router.get("/admins", response_class=HTMLResponse)
def admins_list(request: Request, db: Session = Depends(get_db)):
    sess = require_role(request, "admin")
    admins = db.scalars(select(Admin).order_by(Admin.created_at.desc())).all()
    admins_admin_count = db.scalar(select(func.count()).select_from(Admin).where(Admin.role == "admin")) or 0
    return templates.TemplateResponse("admins_list.html", {"request": request, "sess": sess, "admins": admins, "admins_admin_count": admins_admin_count})


@router.get("/admins/new", response_class=HTMLResponse)
def admin_new_page(request: Request):
    sess = require_role(request, "admin")
    return templates.TemplateResponse("admin_new.html", {"request": request, "sess": sess})


@router.post("/admins/new")
def admin_new_action(
    request: Request,
    login: str = Form(...),
    password: str = Form(...),
    role: str = Form("operator"),
    csrf: str = Form(""),
    db: Session = Depends(get_db),
):
    sess = require_role(request, "admin")
    require_csrf(sess, csrf)

    login = (login or "").strip()
    if not login or len(login) > 50:
        return templates.TemplateResponse("admin_new.html", {"request": request, "sess": sess, "error": "Некорректный логин."}, status_code=400)

    ok, err = password_length_ok(password)
    if not ok:
        return templates.TemplateResponse("admin_new.html", {"request": request, "sess": sess, "error": err}, status_code=400)

    role_map = {"operator": "operator", "admin": "admin"}
    role = role_map.get(role, "operator")

    exists = db.scalar(select(Admin).where(Admin.username == login))
    if exists:
        return templates.TemplateResponse("admin_new.html", {"request": request, "sess": sess, "error": "Такой логин уже существует."}, status_code=400)

    admin = Admin(username=login, password_hash=hash_password(password), role=role)
    db.add(admin)
    db.commit()
    return _redirect("/admins")


@router.post("/admins/{admin_id}/delete")
def admin_delete_action(
    request: Request,
    admin_id: int,
    csrf: str = Form(""),
    db: Session = Depends(get_db),
):
    sess = require_role(request, "admin")
    require_csrf(sess, csrf)

    target = db.get(Admin, admin_id)
    if not target:
        return _redirect("/admins")

    if target.id == sess["admin_id"]:
        admins = db.scalars(select(Admin).order_by(Admin.created_at.desc())).all()
        admins_admin_count = db.scalar(select(func.count()).select_from(Admin).where(Admin.role == "admin")) or 0
        return templates.TemplateResponse(
            "admins_list.html",
            {"request": request, "sess": sess, "admins": admins, "admins_admin_count": admins_admin_count, "error": "Нельзя удалить текущего пользователя."},
            status_code=400,
        )

    if target.role == "admin":
        admins_admin_count = db.scalar(select(func.count()).select_from(Admin).where(Admin.role == "admin")) or 0
        if admins_admin_count <= 1:
            admins = db.scalars(select(Admin).order_by(Admin.created_at.desc())).all()
            return templates.TemplateResponse(
                "admins_list.html",
                {"request": request, "sess": sess, "admins": admins, "admins_admin_count": admins_admin_count, "error": "Нельзя удалить последнего администратора."},
                status_code=400,
            )

    db.delete(target)
    db.commit()
    return _redirect("/admins")


@router.get("/me/password", response_class=HTMLResponse)
def change_password_page(request: Request):
    sess = require_login(request)
    return templates.TemplateResponse("change_password.html", {"request": request, "sess": sess})


@router.post("/me/password")
def change_password_action(
    request: Request,
    current_password: str = Form(...),
    new_password: str = Form(...),
    new_password2: str = Form(...),
    csrf: str = Form(""),
    db: Session = Depends(get_db),
):
    sess = require_login(request)
    require_csrf(sess, csrf)

    admin = db.get(Admin, sess["admin_id"])
    if not admin:
        return _redirect("/login")

    if not verify_password(current_password, admin.password_hash):
        return templates.TemplateResponse(
            "change_password.html",
            {"request": request, "sess": sess, "error": "Текущий пароль неверный."},
            status_code=400,
        )

    if new_password != new_password2:
        return templates.TemplateResponse(
            "change_password.html",
            {"request": request, "sess": sess, "error": "Новые пароли не совпадают."},
            status_code=400,
        )

    ok, err = password_length_ok(new_password)
    if not ok:
        return templates.TemplateResponse(
            "change_password.html",
            {"request": request, "sess": sess, "error": err},
            status_code=400,
        )

    admin.password_hash = hash_password(new_password)
    db.commit()

    try:
        token = request.cookies.get(get_cookie_name(), "")
        if token:
            sessions.rotate_csrf(token)
    except Exception:
        pass

    return templates.TemplateResponse(
        "change_password.html",
        {"request": request, "sess": sess, "success": "Пароль успешно изменён."},
    )


@router.get("/questions", response_class=HTMLResponse)
def questions_list(
    request: Request,
    db: Session = Depends(get_db),
    q: str = Query(default="", max_length=200),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=5, le=100),
    from_id: int = Query(default=0, alias="from"),
):
    sess = require_login(request)

    q = (q or "").strip()
    page_size = clamp(page_size, 5, 100)

    if from_id and not q:
        before_cnt = db.scalar(select(func.count()).select_from(Question).where(Question.id < from_id)) or 0
        page = (before_cnt // page_size) + 1

    page = max(1, page)
    offset = (page - 1) * page_size

    a_min = (
        select(Answer.question_id, func.min(Answer.id).label("min_answer_id"))
        .group_by(Answer.question_id)
        .subquery()
    )

    base = (
        select(Question, Answer)
        .outerjoin(a_min, a_min.c.question_id == Question.id)
        .outerjoin(Answer, Answer.id == a_min.c.min_answer_id)
    )

    if q:
        like = f"%{q}%"
        base = base.where(or_(Question.text.like(like), Question.tags.like(like), Answer.text.like(like)))

    total = db.scalar(select(func.count()).select_from(base.subquery())) or 0

    rows = db.execute(base.order_by(Question.id.asc()).offset(offset).limit(page_size)).all()
    items = [{"q": qq, "a": aa} for qq, aa in rows]
    pages = max(1, (total + page_size - 1) // page_size)

    return templates.TemplateResponse(
        "questions_list.html",
        {
            "request": request,
            "sess": sess,
            "items": items,
            "query": q,
            "page": page,
            "page_size": page_size,
            "pages": pages,
            "total": total,
            "from_id": from_id,
        },
    )


@router.get("/questions/new", response_class=HTMLResponse)
def question_new_page(request: Request):
    sess = require_login(request)
    return templates.TemplateResponse("question_new.html", {"request": request, "sess": sess})


@router.post("/questions/new")
async def question_new_action(
    request: Request,
    text: str = Form(...),
    answer_text: str = Form(...),
    tags: str = Form(""),
    csrf: str = Form(""),
    files: Union[UploadFile, List[UploadFile], None] = File(default=None),
    db: Session = Depends(get_db),
):
    sess = require_login(request)
    require_csrf(sess, csrf)

    try:
        text = validate_question_text(text)
        answer_text = validate_answer_text(answer_text)
        tags_csv, _ = parse_tags(tags)
    except ValueError as e:
        return templates.TemplateResponse(
            "question_new.html",
            {"request": request, "sess": sess, "error": str(e), "text": text, "answer_text": answer_text, "tags": tags},
            status_code=400,
        )

    files_list = _normalize_files(files)

    media_ids: List[int] = []
    if files_list:
        try:
            media_ids = await save_images(files_list)
        except ValueError as e:
            return templates.TemplateResponse(
                "question_new.html",
                {"request": request, "sess": sess, "error": str(e), "text": text, "answer_text": answer_text, "tags": tags},
                status_code=400,
            )

    try:
        emb = await _embed_with_timeout(text, seconds=30)
    except TimeoutError:
        delete_media_files(media_ids)
        return templates.TemplateResponse(
            "question_new.html",
            {"request": request, "sess": sess, "error": "Генерация embedding заняла слишком много времени (таймаут 30с).", "text": text, "answer_text": answer_text, "tags": tags},
            status_code=500,
        )
    except Exception as e:
        delete_media_files(media_ids)
        log.exception("Embedding error on question create")
        return templates.TemplateResponse(
            "question_new.html",
            {"request": request, "sess": sess, "error": f"Ошибка генерации embedding: {type(e).__name__}: {str(e)}", "text": text, "answer_text": answer_text, "tags": tags},
            status_code=500,
        )

    try:
        qid = _insert_question_with_vector(db, text, tags_csv or None, emb)
        a = Answer(question_id=qid, text=answer_text, visual_path=media_ids or None)
        db.add(a)
        db.commit()
    except Exception:
        log.exception("DB error on question create")
        db.rollback()
        delete_media_files(media_ids)
        return templates.TemplateResponse(
            "question_new.html",
            {"request": request, "sess": sess, "error": "Ошибка сохранения в БД.", "text": text, "answer_text": answer_text, "tags": tags},
            status_code=500,
        )

    return RedirectResponse(url=_u(f"/questions/{qid}"), status_code=303)


@router.get("/questions/{question_id}", response_class=HTMLResponse)
def question_detail(request: Request, question_id: int, db: Session = Depends(get_db)):
    sess = require_login(request)

    q_obj = db.get(Question, question_id)
    if not q_obj:
        return templates.TemplateResponse("error.html", {"request": request, "sess": sess, "error": "Вопрос не найден."}, status_code=404)

    a = _get_single_answer(db, question_id)

    prev_id = db.scalar(select(func.max(Question.id)).where(Question.id < question_id))
    next_id = db.scalar(select(func.min(Question.id)).where(Question.id > question_id))

    return templates.TemplateResponse(
        "question_detail.html",
        {"request": request, "sess": sess, "q": q_obj, "a": a, "prev_id": prev_id, "next_id": next_id},
    )


@router.get("/questions/{question_id}/edit", response_class=HTMLResponse)
def question_edit_page(request: Request, question_id: int, db: Session = Depends(get_db)):
    sess = require_login(request)
    q_obj = db.get(Question, question_id)
    if not q_obj:
        return templates.TemplateResponse("error.html", {"request": request, "sess": sess, "error": "Вопрос не найден."}, status_code=404)
    a = _get_single_answer(db, question_id)
    return templates.TemplateResponse("question_edit.html", {"request": request, "sess": sess, "q": q_obj, "a": a})


@router.post("/questions/{question_id}/edit")
async def question_edit_action(
    request: Request,
    question_id: int,
    text: str = Form(...),
    answer_text: str = Form(...),
    tags: str = Form(""),
    csrf: str = Form(""),
    delete_media: Optional[List[str]] = Form(default=None),
    files: Union[UploadFile, List[UploadFile], None] = File(default=None),
    db: Session = Depends(get_db),
):
    sess = require_login(request)
    require_csrf(sess, csrf)

    q_obj = db.get(Question, question_id)
    if not q_obj:
        return _redirect("/questions")

    a = _get_single_answer(db, question_id)

    try:
        text = validate_question_text(text)
        answer_text = validate_answer_text(answer_text)
        tags_csv, _ = parse_tags(tags)
    except ValueError as e:
        return templates.TemplateResponse("question_edit.html", {"request": request, "sess": sess, "q": q_obj, "a": a, "error": str(e)}, status_code=400)

    text_changed = (text != q_obj.text)

    try:
        if text_changed:
            emb = await _embed_with_timeout(text, seconds=30)
            _update_question_with_vector(db, question_id, text, tags_csv or None, emb)
        else:
            db.execute(sql_text("UPDATE questions SET text=:text, tags=:tags WHERE id=:id"), {"id": question_id, "text": text, "tags": tags_csv or None})
    except Exception as e:
        log.exception("Question update error")
        return templates.TemplateResponse(
            "question_edit.html",
            {"request": request, "sess": sess, "q": q_obj, "a": a, "error": f"Ошибка обновления вопроса: {type(e).__name__}: {str(e)}"},
            status_code=500,
        )

    q_obj = db.get(Question, question_id)

    if not a:
        a = Answer(question_id=question_id, text=answer_text, visual_path=None)
        db.add(a)
        db.flush()

    current = list(a.visual_path or [])

    to_delete = set()
    for x in (delete_media or []):
        try:
            to_delete.add(int(x))
        except Exception:
            pass

    if to_delete:
        keep = [x for x in current if int(x) not in to_delete]
        delete_media_files([x for x in current if int(x) in to_delete])
        current = keep

    files_list = _normalize_files(files)
    if files_list:
        try:
            new_ids = await save_images(files_list)
        except ValueError as e:
            db.rollback()
            return templates.TemplateResponse("question_edit.html", {"request": request, "sess": sess, "q": q_obj, "a": a, "error": str(e)}, status_code=400)
        current.extend(new_ids)

    a.text = answer_text
    a.visual_path = current or None

    db.commit()
    return RedirectResponse(url=_u(f"/questions/{question_id}"), status_code=303)


@router.get("/questions/{question_id}/answer/edit")
def answer_edit_redirect(question_id: int):
    return RedirectResponse(url=_u(f"/questions/{question_id}/edit"), status_code=303)


@router.post("/questions/{question_id}/delete")
def question_delete_action(
    request: Request,
    question_id: int,
    csrf: str = Form(""),
    db: Session = Depends(get_db),
):
    sess = require_login(request)
    require_csrf(sess, csrf)

    q_obj = db.get(Question, question_id)
    if not q_obj:
        return _redirect("/questions")

    a = _get_single_answer(db, question_id)
    if a:
        delete_media_files(a.visual_path)

    db.delete(q_obj)
    db.commit()
    return _redirect("/questions")