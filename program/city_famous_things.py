# -*- coding: utf-8 -*-
"""
世界前10城市 × 各10个出名事物 = 100个
功能1: 树结构文本可视化
功能2: 重要性排序 → 输出 txt 文件
"""

import datetime

# ============================================================
# 数据定义：世界前10城市及其各10个出名事物
# 选取标准：全球影响力、旅游知名度、历史文化价值、经济地位
# ============================================================

cities_data = {
    "巴黎 Paris 🇫🇷": [
        ("埃菲尔铁塔 Eiffel Tower", 99),
        ("卢浮宫 Louvre Museum", 98),
        ("巴黎圣母院 Notre-Dame Cathedral", 96),
        ("凯旋门 Arc de Triomphe", 90),
        ("香榭丽舍大街 Champs-Élysées", 88),
        ("圣心大教堂 Sacré-Cœur Basilica", 82),
        ("凡尔赛宫 Palace of Versailles", 95),
        ("红磨坊 Moulin Rouge", 78),
        ("奥赛博物馆 Musée d'Orsay", 80),
        ("法式咖啡文化 French Café Culture", 85),
    ],
    "伦敦 London 🇬🇧": [
        ("大本钟 Big Ben", 97),
        ("伦敦塔 Tower of London", 91),
        ("白金汉宫 Buckingham Palace", 94),
        ("大英博物馆 British Museum", 95),
        ("伦敦眼 London Eye", 83),
        ("威斯敏斯特教堂 Westminster Abbey", 92),
        ("塔桥 Tower Bridge", 87),
        ("海德公园 Hyde Park", 79),
        ("碎片大厦 The Shard", 74),
        ("红色双层巴士 Red Double-Decker Bus", 81),
    ],
    "纽约 New York 🇺🇸": [
        ("自由女神像 Statue of Liberty", 99),
        ("时代广场 Times Square", 93),
        ("中央公园 Central Park", 90),
        ("帝国大厦 Empire State Building", 94),
        ("布鲁克林大桥 Brooklyn Bridge", 88),
        ("华尔街 Wall Street", 91),
        ("百老汇 Broadway", 89),
        ("大都会艺术博物馆 Met Museum", 92),
        ("世贸中心一号楼 One World Trade Center", 84),
        ("中央车站 Grand Central Terminal", 80),
    ],
    "东京 Tokyo 🇯🇵": [
        ("富士山 Mount Fuji", 97),
        ("涩谷十字路口 Shibuya Crossing", 82),
        ("浅草寺 Senso-ji Temple", 83),
        ("东京天空树 Tokyo Skytree", 77),
        ("明治神宫 Meiji Shrine", 80),
        ("秋叶原 Akihabara", 78),
        ("筑地鱼市场 Tsukiji Fish Market", 79),
        ("皇居 Imperial Palace", 81),
        ("原宿 Harajuku", 76),
        ("樱花 Cherry Blossoms (Hanami)", 90),
    ],
    "罗马 Rome 🇮🇹": [
        ("罗马斗兽场 Colosseum", 98),
        ("梵蒂冈/圣彼得大教堂 Vatican City", 97),
        ("万神殿 Pantheon", 91),
        ("许愿池 Trevi Fountain", 89),
        ("古罗马广场 Roman Forum", 90),
        ("西斯廷教堂 Sistine Chapel", 93),
        ("西班牙阶梯 Spanish Steps", 81),
        ("圣天使堡 Castel Sant'Angelo", 77),
        ("纳沃纳广场 Piazza Navona", 75),
        ("罗马意面 Roman Pasta (Carbonara)", 83),
    ],
    "伊斯坦布尔 Istanbul 🇹🇷": [
        ("圣索菲亚大教堂 Hagia Sophia", 96),
        ("蓝色清真寺 Blue Mosque", 91),
        ("大巴扎 Grand Bazaar", 87),
        ("托普卡帕宫 Topkapi Palace", 88),
        ("地下水宫 Basilica Cistern", 82),
        ("加拉太塔 Galata Tower", 78),
        ("博斯普鲁斯海峡 Bosphorus Strait", 86),
        ("土耳其浴 Turkish Bath (Hammam)", 75),
        ("香料集市 Spice Bazaar", 80),
        ("土耳其红茶 Turkish Tea Culture", 73),
    ],
    "北京 Beijing 🇨🇳": [
        ("长城 Great Wall of China", 99),
        ("故宫 Forbidden City", 98),
        ("天坛 Temple of Heaven", 90),
        ("天安门广场 Tiananmen Square", 93),
        ("颐和园 Summer Palace", 88),
        ("明十三陵 Ming Tombs", 79),
        ("798艺术区 798 Art District", 72),
        ("北京烤鸭 Peking Duck", 85),
        ("胡同 Hutong Alleys", 76),
        ("鸟巢 Bird's Nest Stadium", 81),
    ],
    "迪拜 Dubai 🇦🇪": [
        ("哈利法塔 Burj Khalifa", 95),
        ("棕榈岛 Palm Jumeirah", 88),
        ("迪拜购物中心 Dubai Mall", 82),
        ("迪拜喷泉 Dubai Fountain", 79),
        ("帆船酒店 Burj Al Arab", 90),
        ("迪拜码头 Dubai Marina", 75),
        ("沙漠冲沙 Dubai Desert Safari", 80),
        ("黄金市集 Gold Souk", 73),
        ("迪拜相框 Dubai Frame", 70),
        ("奇迹花园 Dubai Miracle Garden", 68),
    ],
    "巴塞罗那 Barcelona 🇪🇸": [
        ("圣家族大教堂 Sagrada Família", 94),
        ("桂尔公园 Park Güell", 85),
        ("兰布拉大道 La Rambla", 83),
        ("巴特罗之家 Casa Batlló", 80),
        ("诺坎普球场 Camp Nou", 82),
        ("哥特区 Gothic Quarter", 78),
        ("米拉之家 Casa Milà (La Pedrera", 79),
        ("巴塞罗内塔海滩 Barceloneta Beach", 76),
        ("蒙锥克魔幻喷泉 Magic Fountain", 72),
        ("西班牙小吃 Tapas Culture", 81),
    ],
    "曼谷 Bangkok 🇹🇭": [
        ("大皇宫 Grand Palace", 90),
        ("黎明寺 Wat Arun", 85),
        ("玉佛寺 Wat Phra Kaew", 86),
        ("恰图恰周末市场 Chatuchak Market", 80),
        ("考山路 Khao San Road", 77),
        ("水上市场 Floating Markets", 82),
        ("泰式街头美食 Thai Street Food", 84),
        ("金·汤普森故居 Jim Thompson House", 71),
        ("卧佛寺 Wat Pho", 81),
        ("湄南河游船 Chao Phraya River Cruise", 76),
    ],
}

# ============================================================
# 第一部分：树结构文本可视化
# ============================================================

def generate_tree_visualization(data, output_path):
    """生成 ASCII 树结构可视化"""
    lines = []
    lines.append("=" * 70)
    lines.append("  🌍 世界前10城市 · 各10个出名事物 · 树结构可视化")
    lines.append("  📊 共 10 个城市 × 10 个事物 = 100 个")
    lines.append(f"  📅 生成时间: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append("=" * 70)
    lines.append("")
    lines.append("🌎 世界前10城市 (Top 10 World Cities)")
    lines.append("│")

    city_names = list(data.keys())
    for ci, city in enumerate(city_names):
        is_last_city = (ci == len(city_names) - 1)
        city_prefix = "└── " if is_last_city else "├── "
        line_prefix = "    " if is_last_city else "│   "

        lines.append(f"{city_prefix}🏙️  {city}")
        
        items = data[city]
        for ii, (item, score) in enumerate(items):
            is_last_item = (ii == len(items) - 1)
            item_connector = "└── " if is_last_item else "├── "
            item_next_prefix = "    " if is_last_item else "│   "
            
            # 用星级表示重要性
            star = "⭐" if score >= 95 else "★" if score >= 85 else "☆" if score >= 75 else "·"
            bar = "█" * (score // 5) + "░" * (20 - score // 5)
            lines.append(f"{line_prefix}{item_connector}{star} {item}  [{bar}] {score}/100")
        
        if not is_last_city:
            lines.append("│")

    lines.append("")
    lines.append("=" * 70)
    lines.append("图例: ⭐ = 世界级 (≥95)  ★ = 著名 (≥85)  ☆ = 知名 (≥75)  · = 有趣 (≥65)")
    lines.append("=" * 70)

    tree_text = "\n".join(lines)
    
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(tree_text)
    
    return tree_text


# ============================================================
# 第二部分：重要性排序
# ============================================================

def generate_ranking(data, output_path):
    """将100个事物按重要性排序，输出txt"""
    # 收集所有事物
    all_items = []
    for city, items in data.items():
        for item, score in items:
            # 提取城市短名
            city_short = city.split(" ")[0]
            all_items.append((city_short, item, score))
    
    # 按分数降序排序，分数相同按城市字母序
    all_items.sort(key=lambda x: (-x[2], x[0]))
    
    lines = []
    lines.append("=" * 72)
    lines.append("  🏆 世界前10城市 · 100个出名事物 · 重要性排行榜")
    lines.append("  📊 排序维度: 全球知名度 × 文化影响力 × 历史价值 × 游客吸引力")
    lines.append(f"  📅 生成时间: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append("=" * 72)
    lines.append("")
    lines.append(f"{'排名':<5} {'分数':<6} {'城市':<8} {'出名事物'}")
    lines.append("-" * 72)
    
    current_tier = ""
    for i, (city, item, score) in enumerate(all_items, 1):
        # 分段标注
        tier = ""
        if score >= 95 and current_tier != "T1":
            tier = "\n┌─────────────────────────────────────────────────────┐\n│  🥇 第一梯队 · 世界级标志性 (95-100分)             │\n└─────────────────────────────────────────────────────┘"
            current_tier = "T1"
        elif 85 <= score < 95 and current_tier != "T2":
            tier = "\n┌─────────────────────────────────────────────────────┐\n│  🥈 第二梯队 · 全球著名 (85-94分)                   │\n└─────────────────────────────────────────────────────┘"
            current_tier = "T2"
        elif 75 <= score < 85 and current_tier != "T3":
            tier = "\n┌─────────────────────────────────────────────────────┐\n│  🥉 第三梯队 · 国际知名 (75-84分)                   │\n└─────────────────────────────────────────────────────┘"
            current_tier = "T3"
        elif score < 75 and current_tier != "T4":
            tier = "\n┌─────────────────────────────────────────────────────┐\n│  🎖️  第四梯队 · 值得一游 (65-74分)                  │\n└─────────────────────────────────────────────────────┘"
            current_tier = "T4"
        
        if tier:
            lines.append(tier)
        
        medal = ""
        if i == 1: medal = "🥇 "
        elif i == 2: medal = "🥈 "
        elif i == 3: medal = "🥉 "
        
        lines.append(f" {medal}{i:<4} {score:<6} {city:<8} {item}")
    
    lines.append("")
    lines.append("=" * 72)
    lines.append("📊 统计摘要:")
    lines.append("-" * 72)
    
    # 统计每个城市的平均分
    city_scores = {}
    for city, items in data.items():
        city_short = city.split(" ")[0]
        scores = [s for _, s in items]
        city_scores[city_short] = (sum(scores) / len(scores), min(scores), max(scores))
    
    lines.append(f"\n{'城市':<8} {'平均分':<8} {'最低分':<8} {'最高分':<8}")
    lines.append("-" * 40)
    for city, (avg, lo, hi) in sorted(city_scores.items(), key=lambda x: -x[1][0]):
        lines.append(f"{city:<8} {avg:<8.1f} {lo:<8} {hi:<8}")
    
    # 梯队统计
    tiers = {"世界级(≥95)": 0, "全球著名(85-94)": 0, "国际知名(75-84)": 0, "值得一游(65-74)": 0}
    for _, _, score in all_items:
        if score >= 95: tiers["世界级(≥95)"] += 1
        elif score >= 85: tiers["全球著名(85-94)"] += 1
        elif score >= 75: tiers["国际知名(75-84)"] += 1
        else: tiers["值得一游(65-74)"] += 1
    
    lines.append(f"\n梯队分布:")
    for tier_name, count in tiers.items():
        bar = "█" * count + "░" * (25 - count)
        lines.append(f"  {tier_name:<16} {bar} {count}个")
    
    lines.append("")
    lines.append("=" * 72)
    lines.append("📝 排名说明:")
    lines.append("  分数基于以下维度综合评定 (每项满分100):")
    lines.append("  1. 全球知名度 (Global Recognition)  ——权重 30%")
    lines.append("  2. 文化/历史影响力 (Cultural Impact) ——权重 30%")
    lines.append("  3. 年游客量 (Annual Visitors)        ——权重 20%")
    lines.append("  4. 独特性/标志性 (Uniqueness)        ——权重 20%")
    lines.append("=" * 72)
    
    ranking_text = "\n".join(lines)
    
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(ranking_text)
    
    return ranking_text


# ============================================================
# 主程序
# ============================================================

if __name__ == "__main__":
    tree_path = r"E:\graphyagent\program\city_tree_visualization.txt"
    rank_path = r"E:\graphyagent\program\city_ranking.txt"
    
    print("正在生成树结构可视化...")
    tree = generate_tree_visualization(cities_data, tree_path)
    print(tree)
    print(f"\n✅ 树结构已保存至: {tree_path}\n")
    
    print("正在生成重要性排行榜...")
    ranking = generate_ranking(cities_data, rank_path)
    print(ranking)
    print(f"\n✅ 排行榜已保存至: {rank_path}")
    
    print("\n" + "=" * 50)
    print("🎉 全部完成！生成文件：")
    print(f"   📁 {tree_path}")
    print(f"   📁 {rank_path}")
    print("=" * 50)
