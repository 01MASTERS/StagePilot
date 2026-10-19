import csv
import json
import os
from collections import defaultdict, Counter
from datetime import datetime, timezone, timedelta

UTC = timezone.utc
IST = timezone(timedelta(hours=5, minutes=30))

pack = r"c:\Users\ravis\OneDrive\Desktop\StageAI\docs\one_user_one_agent_pack"

def ts(s):
    return datetime.fromisoformat(s.replace('Z', '+00:00')) if s else None

print("=== 1. PROFILES SNAPSHOT ANALYSIS ===")
profiles_by_user = defaultdict(list)
profile_file = os.path.join(pack, "data/profiles_snapshot.csv")
with open(profile_file, encoding="utf-8") as f:
    reader = csv.DictReader(f)
    for row in reader:
        profiles_by_user[row["user_id"]].append(row)

total_rows = sum(len(v) for v in profiles_by_user.values())
dup_users = {u: rows for u, rows in profiles_by_user.items() if len(rows) > 1}
print(f"Total profile rows: {total_rows}, Unique users: {len(profiles_by_user)}, Duplicates: {len(dup_users)}")
for u, rows in list(dup_users.items())[:3]:
    print(f"Sample duplicate user {u}:")
    for r in rows:
        print(f"  updated_at={r['updated_at']}, status={r['subscription_status']}, dialect={r['preferred_dialect']}")

print("\n=== 2. PILOT REPORT RE-ANALYSIS (ITT VS CLAIMED) ===")
pilot_arms = {}
with open(os.path.join(pack, "pilot/pilot_assignment.csv"), encoding="utf-8") as f:
    for r in csv.DictReader(f):
        pilot_arms[r["user_id"]] = r

pilot_outcomes = {}
with open(os.path.join(pack, "pilot/pilot_outcomes.csv"), encoding="utf-8") as f:
    for r in csv.DictReader(f):
        pilot_outcomes[r["user_id"]] = r

treatment = [u for u, r in pilot_arms.items() if r["arm"] == "treatment"]
holdout = [u for u, r in pilot_arms.items() if r["arm"] == "holdout"]
served = [u for u, r in pilot_arms.items() if r["served"] == "true"]
unserved = [u for u, r in pilot_arms.items() if r["served"] == "false"]
other = [u for u in pilot_arms if u not in served]

def get_stats(user_list):
    succ = sum(1 for u in user_list if pilot_outcomes.get(u, {}).get("succeeded") == "true")
    n = len(user_list)
    rate = succ / n if n else 0
    return succ, n, rate

s_succ, s_n, s_rate = get_stats(served)
o_succ, o_n, o_rate = get_stats(other)
t_succ, t_n, t_rate = get_stats(treatment)
h_succ, h_n, h_rate = get_stats(holdout)
u_succ, u_n, u_rate = get_stats(unserved)

print(f"Report Claim: Served ({s_succ}/{s_n} = {s_rate:.2%}) vs Other ({o_succ}/{o_n} = {o_rate:.2%}) -> Diff = {(s_rate - o_rate)*100:+.2f} points (Claimed 2.3x uplift)")
print(f"True ITT: Treatment ({t_succ}/{t_n} = {t_rate:.2%}) vs Holdout ({h_succ}/{h_n} = {h_rate:.2%}) -> Diff = {(t_rate - h_rate)*100:+.2f} points")
print(f"Selection Bias detail: Unserved in treatment ({u_succ}/{u_n} = {u_rate:.2%}), Holdout ({h_succ}/{h_n} = {h_rate:.2%})")

print("\n=== 3. CATALOGUE AND EPISODES ANALYSIS ===")
titles = {}
slug_to_titles = defaultdict(list)
with open(os.path.join(pack, "data/catalogue.csv"), encoding="utf-8") as f:
    for r in csv.DictReader(f):
        titles[r["title_id"]] = r
        slug_to_titles[r["content_slug"]].append(r)

multi_title_slugs = {s: tids for s, tids in slug_to_titles.items() if len(tids) > 1}
print(f"Total titles: {len(titles)}, Unique slugs: {len(slug_to_titles)}, Multi-title slugs: {len(multi_title_slugs)}")
for s, rows in list(multi_title_slugs.items())[:3]:
    print(f"  Slug {s}: dialects = {[r['dialect'] for r in rows]}, title_ids = {[r['title_id'] for r in rows]}")

episodes = defaultdict(list)
with open(os.path.join(pack, "data/episodes.csv"), encoding="utf-8") as f:
    for r in csv.DictReader(f):
        episodes[r["content_slug"]].append(r)
print(f"Total episodes rows: {sum(len(v) for v in episodes.values())}, Slugs with episodes: {len(episodes)}")

print("\n=== 4. REPLAY TRIGGERS AND ANOMALIES ===")
triggers = []
trigger_users = set()
with open(os.path.join(pack, "replay/triggers.jsonl"), encoding="utf-8") as f:
    for line in f:
        triggers.append(json.loads(line))
        trigger_users.add(triggers[-1]["user_id"])

print(f"Total triggers: {len(triggers)}, Unique users triggered: {len(trigger_users)}")

# Clock skew and offline buffering in triggers
stale_triggers = []
for t in triggers:
    rec = ts(t["received_at"])
    occ = ts(t["occurred_at"])
    sent = ts(t["sent_at"])
    deliv = ts(t["deliver_at"])
    true_t = rec - (sent - occ)
    age_s = (rec - true_t).total_seconds()
    if age_s > 600:
        stale_triggers.append((t["event_id"], t["user_id"], age_s))

print(f"Triggers with buffer delay > 10 min: {len(stale_triggers)}")
if stale_triggers:
    print(f"  Max buffer delay: {max(s[2] for s in stale_triggers)/3600:.1f} hours, min: {min(s[2] for s in stale_triggers)/60:.1f} minutes")

# Check missing profiles for triggered users
missing_profiles = [u for u in trigger_users if u not in profiles_by_user]
print(f"Triggered users with NO profile in profiles_snapshot: {len(missing_profiles)}")

# Check replay arms distribution
replay_arms = {}
with open(os.path.join(pack, "replay/arms.csv"), encoding="utf-8") as f:
    for r in csv.DictReader(f):
        replay_arms[r["user_id"]] = r["arm"]

arm_counts = Counter(replay_arms[u] for u in trigger_users if u in replay_arms)
print(f"Triggered users by arm: {arm_counts}")

print("\n=== 5. CONTROL EVENTS & MODEL FAULTS ===")
with open(os.path.join(pack, "replay/control_events.jsonl"), encoding="utf-8") as f:
    for i, line in enumerate(f):
        c = json.loads(line)
        print(f"Control {i+1}: at={c.get('at')} type={c.get('type')} keys={list(c.keys())}")

with open(os.path.join(pack, "replay/model_faults.jsonl"), encoding="utf-8") as f:
    for i, line in enumerate(f):
        m = json.loads(line)
        print(f"Fault {i+1}: user={m.get('user_id')} fault={m.get('fault')}")
