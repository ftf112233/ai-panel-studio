-- AI Panel Studio 数据库初始化脚本（SQLite）
-- 用法： sqlite3 backend/data/roundtable.db < scripts/init_db.sql

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS topics (
    id          TEXT PRIMARY KEY,
    topic       TEXT NOT NULL,
    lineup      TEXT NOT NULL,
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS debates (
    id             TEXT PRIMARY KEY,
    topic          TEXT NOT NULL,
    expert_count   INTEGER NOT NULL,
    lineup         TEXT NOT NULL,
    status         TEXT NOT NULL,
    round          INTEGER DEFAULT 0,
    consensus      TEXT DEFAULT '[]',
    disagreements  TEXT DEFAULT '[]',
    summary        TEXT DEFAULT '',
    created_at     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS messages (
    id           TEXT PRIMARY KEY,
    debate_id    TEXT NOT NULL,
    round        INTEGER NOT NULL,
    speaker_id   TEXT NOT NULL,
    speaker_name TEXT NOT NULL,
    role         TEXT NOT NULL,
    content      TEXT NOT NULL,
    meta         TEXT DEFAULT '{}',
    created_at   TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_msg_debate ON messages(debate_id, id);

-- 至少 5 条高质量样例数据（预设话题 + 对应嘉宾阵容）
INSERT OR REPLACE INTO topics (id, topic, lineup, created_at) VALUES ('seed_ai_junior', 'AI 编程工具会取代初级程序员吗？', '{"host": {"name": "知遥", "title": "主持人"}, "experts": [{"id": "e1", "name": "林一舟", "occupation": "AI 开发者工具", "title": "AI 编程产品创始人", "stance": "三年内初级岗位需求会明显萎缩，先拥抱工具的人形成代差优势", "style": "语速快、爱用类比"}, {"id": "e2", "name": "沈观澜", "occupation": "传统软件交付", "title": "主导过 3 次 AI 落地、两次烂尾的 CTO", "stance": "代码生成只是环节之一，需求澄清与线上责任无法交给模型", "style": "爱用数据泼冷水"}, {"id": "e3", "name": "江野", "occupation": "大模型应用工程", "title": "每天写 Prompt 与评测的工程师", "stance": "不站队，先把评测和回滚做扎实，再谈替代", "style": "务实、爱举踩坑例子"}, {"id": "e4", "name": "陈也", "occupation": "中小企业数字化", "title": "付费用过 6 款 AI 工具的中小企业主", "stance": "只关心能不能少招人、少加班，别的都是虚的", "style": "大白话、讲真金白银"}]}', datetime('now'));
INSERT OR REPLACE INTO topics (id, topic, lineup, created_at) VALUES ('seed_sme_ai', '中小企业现在该不该全员上 AI 工作流？', '{"host": {"name": "知遥", "title": "主持人"}, "experts": [{"id": "e1", "name": "苏未", "occupation": "组织与流程", "title": "参与过企业数字化改造的顾问", "stance": "流程没梳理清楚就上 AI，只会把混乱自动化", "style": "追问责任与边界"}, {"id": "e2", "name": "林一舟", "occupation": "AI 应用创业", "title": "AI SaaS 创业者", "stance": "窗口期有限，先小范围全员试用再收敛", "style": "激进、看机会"}, {"id": "e3", "name": "陈也", "occupation": "中小企业经营", "title": "50 人规模公司老板", "stance": "员工培训成本比软件费用更高，这是真实约束", "style": "算账式表达"}, {"id": "e4", "name": "沈观澜", "occupation": "企业 IT 治理", "title": "负责合规与数据安全的 CTO", "stance": "客户数据外泄的风险必须先于效率被评估", "style": "谨慎、讲风险清单"}]}', datetime('now'));
INSERT OR REPLACE INTO topics (id, topic, lineup, created_at) VALUES ('seed_cost_effect', '大模型应用应该先做效果还是先控成本？', '{"host": {"name": "知遥", "title": "主持人"}, "experts": [{"id": "e1", "name": "江野", "occupation": "推理工程", "title": "负责线上推理成本的工程师", "stance": "先控成本，否则效果再好也上不了线", "style": "摆数字、讲单价"}, {"id": "e2", "name": "林一舟", "occupation": "AI 产品", "title": "以体验口碑取胜的产品负责人", "stance": "先做效果拿到用户，成本随规模优化", "style": "强调增长"}, {"id": "e3", "name": "沈观澜", "occupation": "企业采购", "title": "按 ROI 审批预算的技术管理者", "stance": "没有单位经济性，试点结束就是终点", "style": "算 ROI"}, {"id": "e4", "name": "苏未", "occupation": "可持续与合规", "title": "关注算力与责任的行业研究员", "stance": "成本不能只算钱，能耗与合规也是成本", "style": "温和但坚持"}]}', datetime('now'));
INSERT OR REPLACE INTO topics (id, topic, lineup, created_at) VALUES ('seed_edu_ai', '中小学该不该全面引入 AI 助教？', '{"host": {"name": "知遥", "title": "主持人"}, "experts": [{"id": "e1", "name": "苏未", "occupation": "教育伦理", "title": "科技伦理研究员", "stance": "未成年人的数据与发展权优先于效率", "style": "追问权责"}, {"id": "e2", "name": "林一舟", "occupation": "教育科技", "title": "AI 学习产品创始人", "stance": "师资缺口客观存在，AI 助教是规模化补位", "style": "乐观、讲普及"}, {"id": "e3", "name": "陈也", "occupation": "家长视角", "title": "两个孩子的父亲", "stance": "担心孩子只会问 AI，不会自己思考", "style": "说生活里的例子"}, {"id": "e4", "name": "江野", "occupation": "教学工具研发", "title": "做过课堂试点的一线工程师", "stance": "先做可控的作业辅导场景，别一上来全学科", "style": "讲试点细节"}]}', datetime('now'));
INSERT OR REPLACE INTO topics (id, topic, lineup, created_at) VALUES ('seed_remote_work', '远程办公三年后，我们该回到办公室吗？', '{"host": {"name": "知遥", "title": "主持人"}, "experts": [{"id": "e1", "name": "陈也", "occupation": "团队管理", "title": "全员远程三年的公司负责人", "stance": "远程能招到更好的人，协作靠制度不靠工位", "style": "讲自己公司"}, {"id": "e2", "name": "沈观澜", "occupation": "研发效能", "title": "负责新人培养的技术总监", "stance": "新人成长速度在远程环境明显下降", "style": "讲带人经历"}, {"id": "e3", "name": "苏未", "occupation": "组织行为", "title": "研究团队凝聚力的学者", "stance": "信任靠高频弱连接维持，办公室仍有价值", "style": "引研究结论"}, {"id": "e4", "name": "江野", "occupation": "工程协作", "title": "跨时区协作的工程师", "stance": "混合办公最现实，但必须重设会议规则", "style": "务实、讲机制"}]}', datetime('now'));
