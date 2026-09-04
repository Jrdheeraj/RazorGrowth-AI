from backend.app.db.engine import build_engine
from backend.app.db.session import init_db, get_session_factory
from backend.app.core.config import get_settings
from sqlalchemy import text

settings = get_settings()
engine = build_engine(settings.DATABASE_URL)
init_db(engine)
factory = get_session_factory()

with factory() as db:
    r = db.execute(text("SELECT count(*) FROM merchants")).scalar()
    c = db.execute(text("SELECT count(*) FROM customers")).scalar()
    o = db.execute(text("SELECT count(*) FROM orders")).scalar()
    p = db.execute(text("SELECT count(*) FROM payments")).scalar()
    cap = db.execute(text("SELECT count(*) FROM payments WHERE status='captured'")).scalar()
    fail = db.execute(text("SELECT count(*) FROM payments WHERE status='failed'")).scalar()
    rev = db.execute(text("SELECT coalesce(sum(amount),0) FROM payments WHERE status='captured'")).scalar()
    memb = db.execute(text("SELECT count(*) FROM memberships")).scalar()
    users_count = db.execute(text("SELECT count(*) FROM users")).scalar()
    print(f"merchants={r} customers={c} orders={o} payments={p}")
    print(f"captured={cap} failed={fail} revenue=Rs{rev}")
    print(f"memberships={memb} users={users_count}")
    mdata = db.execute(text("SELECT id, name, slug FROM merchants LIMIT 5")).fetchall()
    for m in mdata:
        print(f"  merchant: {m.name} ({m.slug}) id={m.id}")
    udata = db.execute(text("SELECT u.email, m.role FROM memberships m JOIN users u ON u.id=m.user_id LIMIT 10")).fetchall()
    for u in udata:
        print(f"  user: {u.email} role={u.role}")
    # Check for knowledge docs
    kd = db.execute(text("SELECT count(*) FROM knowledge_documents")).scalar()
    kc = db.execute(text("SELECT count(*) FROM knowledge_chunks")).scalar()
    print(f"knowledge_documents={kd} knowledge_chunks={kc}")
    # Check agent runs
    try:
        ar = db.execute(text("SELECT count(*) FROM agent_runs")).scalar()
        print(f"agent_runs={ar}")
    except Exception:
        print("agent_runs table not accessible")
    # Check debates
    try:
        ad = db.execute(text("SELECT count(*) FROM agent_debates")).scalar()
        print(f"agent_debates={ad}")
    except Exception:
        print("agent_debates table not accessible")
