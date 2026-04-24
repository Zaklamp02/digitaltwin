import sqlite3, json
conn = sqlite3.connect('/Users/sebastiaandenboer/Documents/Tmp_proj/digital_twin/data/knowledge.db')
rows = conn.execute('SELECT id, metadata FROM nodes').fetchall()
bad = []
for node_id, meta in rows:
    try:
        json.loads(meta or '{}')
    except Exception as e:
        print('INVALID:', repr(node_id), repr(meta), str(e))
        bad.append(node_id)
if not bad:
    print('All metadata valid, checked', len(rows))
else:
    print(len(bad), 'bad nodes, fixing...')
    with conn:
        for nid in bad:
            conn.execute("UPDATE nodes SET metadata='{}' WHERE id=?", (nid,))
    print('Fixed.')
conn.close()
