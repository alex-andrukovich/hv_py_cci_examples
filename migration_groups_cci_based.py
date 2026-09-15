import subprocess
from collections import defaultdict, deque
from pyvis.network import Network
import random

# -----------------------------
# Format LDEV HEX value to 0x0000
# -----------------------------
def format_ldev(ldev):
    return f"0x{ldev:04X}"

# -----------------------------
# Parse host groups from RAIDCOM
# -----------------------------
def parse_host_grps(horcm_id):
    host_groups = subprocess.check_output(
        ["raidcom", "get", "host_grp", "-allports", "-fx", "-I" + horcm_id]
    ).decode().splitlines()

    results = []
    for line in host_groups[1:]:
        if not line.strip():
            continue

        parts = line.split()
        port_name = parts[0]
        gid = int(parts[1])
        group_name = parts[2]
        serial_number = parts[3]

        # LDEVs
        get_lun = subprocess.check_output(
            ["raidcom", "get", "lun", "-port", port_name, group_name, "-fx", "-I" + horcm_id]
        ).decode().splitlines()

        ldevs_of_a_host_grp = []
        for lun in get_lun[1:]:
            if not lun.strip():
                continue
            lun_parts = lun.split()
            ldev_int = int(lun_parts[5], 16)
            ldevs_of_a_host_grp.append(ldev_int)

        # WWNs
        get_hba_wwn = subprocess.check_output(
            ["raidcom", "get", "hba_wwn", "-port", port_name, group_name, "-I" + horcm_id]
        ).decode().splitlines()

        wwns_of_a_host_grp = []
        for wwn in get_hba_wwn[1:]:
            if not wwn.strip():
                continue
            wwn_parts = wwn.split()
            hba_wwn = wwn_parts[3]
            wwns_of_a_host_grp.append(hba_wwn)

        if gid != 0:
            results.append({
                "port": port_name,
                # "gid": gid,
                "group_name": group_name,
                "serial_number": serial_number,
                "ldevs": ldevs_of_a_host_grp,
                "wwns": wwns_of_a_host_grp
            })

    return results


# -----------------------------
# Build connectivity graph
# -----------------------------
def group_host_groups(host_groups):
    wwn_to_hg = defaultdict(list)
    ldev_to_hg = defaultdict(list)

    for idx, hg in enumerate(host_groups):
        for w in hg["wwns"]:
            wwn_to_hg[w].append(idx)
        for l in hg["ldevs"]:
            ldev_to_hg[l].append(idx)

    graph = defaultdict(set)

    def connect(mapping):
        for _, hgs in mapping.items():
            for h1 in hgs:
                for h2 in hgs:
                    if h1 != h2:
                        graph[h1].add(h2)
                        graph[h2].add(h1)

    connect(wwn_to_hg)
    connect(ldev_to_hg)

    visited = set()
    groups = []

    for i in range(len(host_groups)):
        if i not in visited:
            queue = deque([i])
            component = []

            while queue:
                node = queue.popleft()
                if node in visited:
                    continue
                visited.add(node)
                component.append(node)
                queue.extend(graph[node])

            groups.append(component)

    return groups


# -----------------------------
# Assign group IDs
# -----------------------------
def assign_group_ids(host_groups):
    groups = group_host_groups(host_groups)
    for group_id, group in enumerate(groups):
        for idx in group:
            host_groups[idx]["group_id"] = group_id
    return host_groups


# -----------------------------
# SHARED HELPER: WWN/LDEV overlap
# -----------------------------
def get_shared_components(hg1, hg2):
    shared_wwns = set(hg1["wwns"]) & set(hg2["wwns"])
    shared_ldevs = set(hg1["ldevs"]) & set(hg2["ldevs"])

    if not shared_wwns and not shared_ldevs:
        return None

    label_parts = []
    if shared_wwns:
        label_parts.append("WWN: " + ", ".join(shared_wwns))
    if shared_ldevs:
        label_parts.append("LDEV: " + ", ".join(format_ldev(x) for x in shared_ldevs))

    label = " | ".join(label_parts)

    # Color coding for visualization
    if shared_wwns and shared_ldevs:
        color = "#9d4edd"  # nebula violet
    elif shared_wwns:
        color = "#4cc9f0"  # electric blue starfield
    else:
        color = "#f72585"  # magenta nebula core

    return {
        "wwns": shared_wwns,
        "ldevs": shared_ldevs,
        "label": label,
        "color": color
    }


# -----------------------------
# Visualization using PyVis
# -----------------------------
def visualize_host_groups(host_groups, output_file="host_groups_graph.html"):
    # If more than 20 items → split into pages
    if len(host_groups) > 20:
        page_size = 20
        for page_num in range(0, len(host_groups), page_size):
            chunk = host_groups[page_num:page_num + page_size]
            page_file = f"host_groups_page_{page_num // page_size + 1}.html"
            visualize_host_groups(chunk, page_file)
        print(f"Split into multiple pages of 20 items each.")
        return

    # Normal single-page behavior below
    net = Network(height="900px", width="100%", bgcolor="#1e1e1e", font_color="white")
    net.force_atlas_2based()

    # Add nodes
    for i, hg in enumerate(host_groups):
        label = (
            f"{hg['group_name']}\n"
            f"Port: {hg['port']}\n"
            f"Serial: {hg['serial_number']}\n"
            f"Group: {hg['group_id']}"
        )
        title = (
            f"{hg['group_name']} | "
            f"Port: {hg['port']} | "
            f"Serial: {hg['serial_number']} | "
            f"WWNs: {', '.join(hg['wwns']) or 'None'} | "
            f"LDEVs: {', '.join(format_ldev(x) for x in hg['ldevs']) or 'None'} | "
            f"Group ID: {hg['group_id']}"
        )

        color = "#{:06x}".format(random.randint(0, 0xFFFFFF))
        net.add_node(i, label=label, title=title, color=color)

    # Add edges
    for i, hg1 in enumerate(host_groups):
        for j, hg2 in enumerate(host_groups):
            if i >= j:
                continue

            shared = get_shared_components(hg1, hg2)
            if shared:
                net.add_edge(
                    i,
                    j,
                    label=shared["label"],
                    title=shared["label"],
                    color=shared["color"],
                    width=2,
                    font={"size": 10}
                )

    # Write base HTML
    net.write_html(output_file)

    # Inject interactive controls
    controls_html = """
    <style>
    input[type=range] {
        -webkit-appearance: none;
        width: 150px;
        height: 6px;
        background: #ff69b4;
        border-radius: 5px;
        outline: none;
    }
    input[type=range]::-webkit-slider-thumb {
        -webkit-appearance: none;
        height: 18px;
        width: 18px;
        background: #ffffff;
        border: 2px solid #ff1493;
        border-radius: 50%;
        cursor: pointer;
    }
    input[type=range]::-moz-range-thumb {
        height: 18px;
        width: 18px;
        background: #ffffff;
        border: 2px solid #ff1493;
        border-radius: 50%;
        cursor: pointer;
    }
    input[type=range]::-moz-range-track {
        background: #ff69b4;
        height: 6px;
        border-radius: 5px;
    }
    </style>

    <div style="position:absolute; top:10px; left:10px; background:#222; padding:15px; color:white; z-index:9999; border-radius:8px;">
        <h3 style="margin-top:0;">Graph Controls</h3>

        <label>Node Color:</label>
        <input type="color" id="nodeColorPicker" value="#FF69B4">
        <button onclick="applyNodeColor()">Apply</button>
        <br><br>

        <label>Node Size:</label>
        <input type="range" id="nodeSizeSlider" min="5" max="50" value="15">
        <button onclick="applyNodeSize()">Apply</button>
        <br><br>

        <label>Edge Width:</label>
        <input type="range" id="edgeWidthSlider" min="1" max="10" value="2">
        <button onclick="applyEdgeWidth()">Apply</button>
        <br><br>

        <button onclick="network.setOptions({ physics: { enabled: false } })">Disable Physics</button>
        <button onclick="network.setOptions({ physics: { enabled: true } })">Enable Physics</button>
        <br><br>

        <button onclick="network.setOptions({ physics: { solver: 'barnesHut' } })">Barnes-Hut</button>
        <button onclick="network.setOptions({ physics: { solver: 'forceAtlas2Based' } })">ForceAtlas2</button>
        <button onclick="network.setOptions({ physics: { solver: 'repulsion' } })">Repulsion</button>
    </div>

    <script>
    function applyNodeColor() {
        let color = document.getElementById("nodeColorPicker").value;
        nodes.forEach(function(n) {
            nodes.update({ id: n.id, color: { background: color } });
        });
    }
    function applyNodeSize() {
        let size = parseInt(document.getElementById("nodeSizeSlider").value);
        nodes.forEach(function(n) {
            nodes.update({ id: n.id, size: size });
        });
    }
    function applyEdgeWidth() {
        let width = parseInt(document.getElementById("edgeWidthSlider").value);
        edges.forEach(function(e) {
            edges.update({ id: e.id, width: width });
        });
    }
    </script>
    """

    with open(output_file, "a") as f:
        f.write(controls_html)

    print(f"Graph saved to {output_file} with interactive controls")




# -----------------------------
# Print groups with shared info
# -----------------------------
def print_groups(host_groups):
    groups = defaultdict(list)

    for hg in host_groups:
        groups[hg["group_id"]].append(hg)

    for group_id, items in groups.items():
        print(f"\n=== Group {group_id} ===")

        for hg in items:
            print(f"  - {hg['group_name']} (port {hg['port']}, serial {hg['serial_number']})")

        print("  Shared components:")
        printed_any = False

        for i in range(len(items)):
            for j in range(i + 1, len(items)):
                hg1 = items[i]
                hg2 = items[j]

                shared = get_shared_components(hg1, hg2)
                if shared:
                    printed_any = True
                    print(f"    * {hg1['group_name']} (serial {hg1['serial_number']}) ↔ "
                          f"{hg2['group_name']} (serial {hg2['serial_number']})")

                    if shared["wwns"]:
                        print(f"        WWN:  {', '.join(shared['wwns'])}")
                    if shared["ldevs"]:
                        print(f"        LDEV: {', '.join(format_ldev(x) for x in shared['ldevs'])}")

        if not printed_any:
            print("    (No shared WWNs or LDEVs — isolated group)")


# -----------------------------
# MAIN
# -----------------------------
storage_a = {
    "ip": "10.0.0.5",
    "horcm_id": "880",
    "horcm_udp": "45880",
    "serial": "placeholder",
    "site": "site_one",
    "role": "P-VOL",
    "username": "maintenance",
    "password": "raid-m155"
}

storage_b = {
    "ip": "10.0.0.6",
    "horcm_id": "881",
    "horcm_udp": "45881",
    "serial": "placeholder",
    "site": "site_two",
    "role": "S-VOL",
    "username": "maintenance",
    "password": "raid-m155"
}

all_host_grps = []
all_host_grps += parse_host_grps(storage_a['horcm_id'])
all_host_grps += parse_host_grps(storage_b['horcm_id'])


print(all_host_grps)
host_groups_with_ids = assign_group_ids(all_host_grps)
print_groups(host_groups_with_ids)
visualize_host_groups(host_groups_with_ids)

sorted_hgs = sorted(host_groups_with_ids, key=lambda x: x["group_id"])
print("\n=== All Host Groups (sorted by group_id) ===")

with open("sorted_host_groups.txt", "w") as f:
    f.write("=== All Host Groups (sorted by group_id) ===\n")

    for hg in sorted_hgs:
        formatted = {
            **hg,
            "ldevs": [format_ldev(x) for x in hg["ldevs"]]
        }

        print(formatted)                     # console output
        f.write(str(formatted) + "\n")       # file output
