"""Database helper — SQLite initialization and connection."""

import sqlite3
import sqlite3 as sqlite3_module
from pathlib import Path
from typing import Optional
from ..config import get_settings

_db: Optional[sqlite3_module.Connection] = None


def get_db() -> sqlite3_module.Connection:
    global _db
    if _db is None:
        settings = get_settings()
        settings.db_path.parent.mkdir(parents=True, exist_ok=True)
        _db = sqlite3.connect(str(settings.db_path), check_same_thread=False)
        _db.row_factory = sqlite3.Row
        _db.execute("PRAGMA journal_mode=WAL")
        _db.execute("PRAGMA foreign_keys=ON")
    return _db


def init_db():
    """Create tables if they don't exist."""
    db = get_db()

    db.executescript("""
        CREATE TABLE IF NOT EXISTS knowledge_base (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            category TEXT NOT NULL DEFAULT '通用',
            content TEXT NOT NULL,
            risk_level TEXT NOT NULL DEFAULT '中',
            tags TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
        );

        CREATE TABLE IF NOT EXISTS documents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            filename TEXT NOT NULL,
            original_name TEXT NOT NULL,
            file_type TEXT NOT NULL,
            file_path TEXT NOT NULL,
            page_count INTEGER DEFAULT 0,
            clause_count INTEGER DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'uploaded',
            created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
        );

        CREATE TABLE IF NOT EXISTS clauses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            doc_id INTEGER NOT NULL,
            clause_index INTEGER NOT NULL,
            content TEXT NOT NULL,
            page_number INTEGER DEFAULT 1,
            section_title TEXT DEFAULT '',
            FOREIGN KEY (doc_id) REFERENCES documents(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS annotations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            clause_id INTEGER NOT NULL,
            kb_entry_id INTEGER,
            kb_title TEXT DEFAULT '',
            match_type TEXT NOT NULL,
            risk_level TEXT DEFAULT '中',
            comment TEXT DEFAULT '',
            suggestion TEXT DEFAULT '',
            created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
            FOREIGN KEY (clause_id) REFERENCES clauses(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS reviews (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            doc_id INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            total_clauses INTEGER DEFAULT 0,
            matched INTEGER DEFAULT 0,
            conflicted INTEGER DEFAULT 0,
            missing_info INTEGER DEFAULT 0,
            high_risk INTEGER DEFAULT 0,
            medium_risk INTEGER DEFAULT 0,
            low_risk INTEGER DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
            FOREIGN KEY (doc_id) REFERENCES documents(id) ON DELETE CASCADE
        );

        -- Knowledge base: imported sources (files / URLs)
        CREATE TABLE IF NOT EXISTS kb_sources (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_type TEXT NOT NULL DEFAULT 'file',  -- 'file' | 'url'
            source_name TEXT NOT NULL,
            source_url TEXT DEFAULT '',
            chunk_count INTEGER DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
        );

        -- Knowledge base: text chunks with embeddings
        CREATE TABLE IF NOT EXISTS kb_chunks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_id INTEGER NOT NULL,
            chunk_index INTEGER NOT NULL,
            content TEXT NOT NULL,
            embedding BLOB,       -- numpy float32 vector serialized
            metadata TEXT DEFAULT '{}',
            FOREIGN KEY (source_id) REFERENCES kb_sources(id) ON DELETE CASCADE
        );

        -- Insert sample knowledge base entries if empty
        INSERT OR IGNORE INTO knowledge_base (id, title, category, content, risk_level, tags)
        VALUES
        (1, '保密义务条款', '保密协议',
         '双方应对在合作期间知悉的对方商业秘密和保密信息承担保密义务，未经对方书面同意，不得向任何第三方披露。保密义务在合同终止后继续有效，期限为三年。',
         '高', '保密,信息安全,NDA'),
        (2, '违约责任条款', '通用',
         '任何一方违反本合同约定的，应向守约方支付合同总金额20%的违约金。违约金不足以弥补守约方损失的，违约方还应赔偿守约方因此遭受的全部实际损失。',
         '高', '违约,赔偿,风险'),
        (3, '知识产权归属', '知识产权',
         '乙方在履行本合同过程中产生的所有知识产权成果，包括但不限于著作权、专利申请权、技术秘密等，均归甲方所有。乙方保证其交付成果不侵犯任何第三方知识产权。',
         '高', 'IP,版权,专利'),
        (4, '争议解决条款', '通用',
         '因本合同引起的或与本合同有关的任何争议，双方应首先友好协商解决。协商不成的，任何一方均有权向合同签订地有管辖权的人民法院提起诉讼。',
         '中', '争议,诉讼,管辖'),
        (5, '不可抗力条款', '通用',
         '因自然灾害、战争、政府行为等不可抗力因素导致合同无法履行的，受影响方应在不可抗力事件发生后七日内书面通知对方，并提供相关证明文件。双方可根据不可抗力的影响协商延期履行或解除合同。',
         '低', '不可抗力,免责'),
        (6, '付款条款', '采购',
         '买方应在收到卖方开具的合法有效增值税专用发票后30个工作日内支付货款。逾期支付的，每逾期一日按应付未付金额的万分之五向卖方支付逾期付款违约金。',
         '中', '付款,发票,账期'),
        (7, '保密期限条款', '保密协议',
         '保密义务期限为自本合同生效之日起五年。保密信息不包括：在披露时已为公众所知的信息、披露前已由接收方合法持有的信息、从有权披露的第三方合法获得的信息。',
         '中', '保密,期限,例外'),
        (8, '竞业限制条款', '劳动法',
         '员工离职后两年内，不得在与原用人单位有竞争关系的企业任职或提供服务。竞业限制期间，原用人单位按月向员工支付竞业限制补偿金，金额为离职前十二个月平均工资的30%。',
         '高', '竞业,劳动法,离职'),
        (9, '数据保护条款', '隐私',
         '数据处理方应采取不低于行业标准的技术和管理措施保护个人信息安全。未经数据主体明确同意，不得将个人信息用于合同约定之外的用途。发生数据泄露事件应在48小时内通知数据控制方。',
         '高', '数据保护,隐私,GDPR,个保法'),
        (10, '合同自动续期条款', '通用',
         '本合同期满前三十日内，如双方均未书面提出不续签，合同将自动续期一年，续期次数不限。续期后的合同条款与本合同保持一致。',
         '中', '续期,自动续约,期限');
    """)

    db.commit()
