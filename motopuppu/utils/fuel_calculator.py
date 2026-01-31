
def calculate_kpl_bulk(entries):
    """
    FuelEntryのリスト(辞書またはオブジェクト)を受け取り、IDをキーとした燃費の辞書を返す。
    entriesは (id, motorcycle_id, total_distance, fuel_volume, is_full_tank) を持つ必要がある。
    entriesは motorcycle_id, total_distance でソートされていることを前提とする。
    
    Args:
        entries: FuelEntryオブジェクト、または同様の属性を持つオブジェクトのリスト。
                 motorcycle_id, total_distance の順で昇順ソートされている必要がある。
    
    Returns:
        dict: { entry_id: kpl_value(float or None) }
    """
    kpl_map = {}
    
    # 車両ごとに処理
    # motorcycle_id -> { 'last_full_entry': entry, 'accumulated_fuel': 0.0 }
    state_map = {}

    for entry in entries:
        # entry can be a Row object from SQLAlchemy query or a FuelEntry model instance
        e_id = entry.id
        m_id = entry.motorcycle_id
        dist = entry.total_distance
        vol = entry.fuel_volume
        is_full = entry.is_full_tank

        if m_id not in state_map:
            state_map[m_id] = {'last_full_entry': None, 'accumulated_fuel': 0.0}
        
        state = state_map[m_id]
        
        # 燃料を加算
        if vol is not None:
             state['accumulated_fuel'] = state.get('accumulated_fuel', 0.0) + float(vol)

        if is_full:
            last_full = state['last_full_entry']
            if last_full:
                distance_diff = dist - last_full.total_distance
                fuel_consumed = state['accumulated_fuel']
                
                if fuel_consumed > 0 and distance_diff > 0:
                    try:
                        kpl = round(float(distance_diff) / float(fuel_consumed), 2)
                        kpl_map[e_id] = kpl
                    except (ZeroDivisionError, TypeError):
                         kpl_map[e_id] = None
                else:
                    kpl_map[e_id] = None

            # 次の区間のためにリセット
            state['last_full_entry'] = entry
            state['accumulated_fuel'] = 0.0
        else:
             # 満タンでない場合、燃費確定しない
             kpl_map[e_id] = None
             
    return kpl_map
