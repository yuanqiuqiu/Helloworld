# streamlit_app.py
## to run:
## streamlit run C:\Users\joanna.wu\python_projects\MISO_auctions\SF_selection_annual.py --server.address 172.16.15.100 --server.port 8501

import streamlit as st
import pandas as pd
import numpy as np
import os

rootpath = r"C:\Users\joanna.wu\python_projects\MISO_auctions"
auction_name = "Annual26Auc"
auction_round = "2"
out_put_path = f"{rootpath}/{auction_name}_{auction_round}"
input_path = os.path.join(rootpath, f"{auction_name}_{auction_round}", "feathers")
round1_input_path = os.path.join(rootpath, f"{auction_name}_1", "feathers")

st.set_page_config(page_title="CPNode - Constraint Sensitivities", layout="wide")


@st.cache_data(show_spinner=False)
def load_matrix(path: str, index_cols):
    """
    Load feather, set index on ['PNODENAME', 'Type'].
    If 'Type' is missing in old files, fill with 'NA'.
    """
    df = pd.read_feather(path)

    if isinstance(index_cols, (list, tuple)):
        for col in index_cols:
            if col not in df.columns:
                if col == "Type":
                    df[col] = "NA"
                else:
                    raise ValueError(f"Missing index column: {col}")
        df = df.set_index(list(index_cols))
    elif isinstance(index_cols, str):
        if index_cols not in df.columns:
            raise ValueError(f"Missing index column: {index_cols}")
        df = df.set_index(index_cols)

    df = df.apply(pd.to_numeric, errors="coerce")
    return df


@st.cache_data(show_spinner=False)
def load_constraints(path: str) -> pd.DataFrame:
    df = pd.read_feather(path)
    df["Name"] = df["Name"].astype(str)

    if "MarginalCost" in df.columns:
        df["MarginalCost"] = pd.to_numeric(df["MarginalCost"], errors="coerce")
    else:
        df["MarginalCost"] = np.nan

    if "DA" in df.columns:
        if pd.api.types.is_bool_dtype(df["DA"]):
            pass
        else:
            df["DA"] = (
                df["DA"]
                .astype(str)
                .str.strip()
                .str.upper()
                .map({"TRUE": True, "FALSE": False, "1": True, "0": False})
            )
    else:
        df["DA"] = False

    df["DA"] = df["DA"].fillna(False).astype(bool)
    return df


@st.cache_data(show_spinner=False)
def load_feather(path: str) -> pd.DataFrame:
    return pd.read_feather(path)


@st.cache_data(show_spinner=False)
def load_auction_round_comparison(path: str) -> pd.DataFrame:
    df = pd.read_feather(path)
    for col in ["DeviceName", "DeviceType", "Direction", "Contingency", "Class", "Compare", "Status"]:
        if col in df.columns:
            df[col] = df[col].astype(str)
    shadow_cols = [c for c in df.columns if c.startswith("Round_") and c.endswith("_ShadowPrice")]
    for col in shadow_cols + ["ShadowPriceChange"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    if "ShadowPriceChange" in df.columns:
        df["AbsMarginalCostChange"] = df["ShadowPriceChange"].abs()
    else:
        df["AbsMarginalCostChange"] = np.nan
    df = df.sort_values("AbsMarginalCostChange", ascending=False).reset_index(drop=True)
    return df


def parse_case_stem(case_sel: str):
    """
    Parse new file naming:
    Sum26_06012026_06182026
    Returns (tou, win_start, win_end)
    """
    parts = case_sel.split("_")
    if len(parts) >= 3:
        tou = "_".join(parts[:-2])
        win_start = parts[-2]
        win_end = parts[-1]
        return tou, win_start, win_end
    return case_sel, None, None


def parse_outage_window(fname: str):
    """
    Example:
    Sum26_06012026_06182026_outages.feather
    -> dict with file, stem, win_start, win_end
    """
    base = fname.replace("_outages.feather", "")
    parts = base.split("_")
    if len(parts) < 3:
        return None

    try:
        win_start = pd.to_datetime(parts[-2], format="%m%d%Y")
        win_end = pd.to_datetime(parts[-1], format="%m%d%Y")
    except Exception:
        return None

    return {
        "file": fname,
        "stem": base,
        "win_start": win_start,
        "win_end": win_end
    }


def prepare_outage_df(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df = df.rename(columns={"maxkv": "maxKV", "durate": "Duration"})

    for c in ["StartDate", "EndDate"]:
        if c in df.columns:
            df[c] = pd.to_datetime(df[c], errors="coerce")

    if "Duration" in df.columns:
        df["Duration"] = pd.to_numeric(df["Duration"], errors="coerce")
        df["Duration"] = df["Duration"].round().astype("Int64")

    if "maxKV" in df.columns:
        df["maxKV"] = pd.to_numeric(df["maxKV"], errors="coerce")
        df["maxKV"] = df["maxKV"].round(1)

    if "FromBusNum" in df.columns:
        df["FromBusNum"] = pd.to_numeric(df["FromBusNum"], errors="coerce").round().astype("Int64")

    if "EMSName" in df.columns:
        df["EMSName"] = df["EMSName"].astype(str).str.strip()
    else:
        df["EMSName"] = ""

    return df


def outage_ems_set(df: pd.DataFrame) -> set:
    if df.empty or "EMSName" not in df.columns:
        return set()
    return set(df["EMSName"].dropna().astype(str).str.strip().unique().tolist())


st.sidebar.header("Data Settings")

if not os.path.exists(input_path):
    st.error(f"Input path does not exist: {input_path}")
    st.stop()

all_files = os.listdir(input_path)

# --------------------------------------------------------------------
# Select ONE case stem based on *_SF.feather
# --------------------------------------------------------------------
# --------------------------------------------------------------------
# Select TOU first, then window
# --------------------------------------------------------------------
sf_files = sorted([f for f in all_files if f.endswith("_SF.feather")])

if not sf_files:
    st.sidebar.warning("No *_SF.feather files found in 'feathers/' folder.")
    st.stop()

case_stems = [f[:-11] for f in sf_files]  # remove "_SF.feather"

case_info = []
for stem in case_stems:
    tou, win_start, win_end = parse_case_stem(stem)
    case_info.append({
        "case_sel": stem,
        "TOU": tou,
        "win_start": win_start,
        "win_end": win_end,
        "window_label": f"{win_start} -> {win_end}" if win_start and win_end else stem
    })

case_info_df = pd.DataFrame(case_info)

tou_options = sorted(case_info_df["TOU"].dropna().unique().tolist())
selected_tou = st.sidebar.selectbox("Select TOU", tou_options, index=0)

tou_case_df = case_info_df[case_info_df["TOU"] == selected_tou].copy()

# sort windows by actual start/end date if possible
def _parse_mmddyyyy(x):
    try:
        return pd.to_datetime(x, format="%m%d%Y")
    except Exception:
        return pd.NaT

tou_case_df["win_start_dt"] = tou_case_df["win_start"].apply(_parse_mmddyyyy)
tou_case_df["win_end_dt"] = tou_case_df["win_end"].apply(_parse_mmddyyyy)
tou_case_df = tou_case_df.sort_values(["win_start_dt", "win_end_dt"]).reset_index(drop=True)

window_options = tou_case_df["window_label"].tolist()
selected_window = st.sidebar.selectbox("Select window", window_options, index=0)

case_sel = tou_case_df.loc[tou_case_df["window_label"] == selected_window, "case_sel"].iloc[0]
tou_name, win_start, win_end = parse_case_stem(case_sel)

st.sidebar.caption(f"TOU: {tou_name}")
if win_start and win_end:
    st.sidebar.caption(f"Window: {win_start} -> {win_end}")


sf_path = os.path.join(input_path, f"{case_sel}_SF.feather")
constr_path = os.path.join(input_path, f"{case_sel}_constraints.feather")
oos_path = os.path.join(input_path, f"{case_sel}_OOS_constraints.feather")
outage_path = os.path.join(input_path, f"{case_sel}_outages.feather")

index_cols = ["PNODENAME", "Type"]

try:
    M = load_matrix(sf_path, index_cols)
except Exception as e:
    st.error(f"Failed to load SF matrix: {e}")
    st.stop()

if os.path.exists(constr_path):
    C = load_constraints(constr_path)
else:
    st.error(f"Missing constraints file: {os.path.basename(constr_path)}")
    st.stop()

if os.path.exists(oos_path):
    OOS = load_constraints(oos_path)
else:
    OOS = pd.DataFrame()

# --------------------------------------------------------------------
# Index prep
# --------------------------------------------------------------------
idx_df = M.index.to_frame(index=False)
if "Type" not in idx_df.columns:
    idx_df["Type"] = "NA"

all_types = sorted(idx_df["Type"].dropna().unique().tolist())

node_type_df = idx_df[["PNODENAME", "Type"]].drop_duplicates().copy()
node_type_df["Label"] = (
    node_type_df["PNODENAME"].astype(str) + " | " + node_type_df["Type"].astype(str)
)

label_to_idx = {
    row["Label"]: (row["PNODENAME"], row["Type"])
    for _, row in node_type_df.iterrows()
}

constraints = M.columns.astype(str).tolist()
num_constr = len(constraints)

# --------------------------------------------------------------------
# Ranked constraints
# --------------------------------------------------------------------
C2 = C.copy()
C2["Name"] = C2["Name"].astype(str)

if "DA" not in C2.columns:
    C2["DA"] = False
C2["DA"] = C2["DA"].fillna(False).astype(bool)

if "MarginalCost" in C2.columns:
    C2["MarginalCost"] = pd.to_numeric(C2["MarginalCost"], errors="coerce")
else:
    C2["MarginalCost"] = np.nan

C2 = C2[C2["Name"].isin(M.columns)]

da_rank = (
    C2[C2["DA"] == True]
    .assign(AbsMarginalCost=lambda d: d["MarginalCost"].abs())
    .sort_values("AbsMarginalCost", ascending=False)
    .reset_index(drop=True)
)
da_rank["Rank"] = np.arange(1, len(da_rank) + 1)
da_rank["Percentile"] = (1 - (da_rank["Rank"] - 1) / max(len(da_rank), 1)) * 100

auction_rank = (
    C2[C2["DA"] == False]
    .assign(AbsMarginalCost=lambda d: d["MarginalCost"].abs())
    .sort_values("AbsMarginalCost", ascending=False)
    .reset_index(drop=True)
)
auction_rank["Rank"] = np.arange(1, len(auction_rank) + 1)
auction_rank["Percentile"] = (1 - (auction_rank["Rank"] - 1) / max(len(auction_rank), 1)) * 100

constraint_meta = pd.concat([
    da_rank[["Name", "Rank", "MarginalCost"]].assign(Set="DA"),
    auction_rank[["Name", "Rank", "MarginalCost"]].assign(Set="Auction")
], ignore_index=True)

constraint_meta = constraint_meta.rename(columns={"Name": "Constraint"})
constraint_meta["Constraint"] = constraint_meta["Constraint"].astype(str)
constraint_meta["Rank"] = pd.to_numeric(constraint_meta["Rank"], errors="coerce").astype("Int64")
constraint_meta["MarginalCost"] = pd.to_numeric(constraint_meta["MarginalCost"], errors="coerce")

# --------------------------------------------------------------------
# Tabs
# --------------------------------------------------------------------
tab1, tab2, tab3, tab4, tab5, tab6, tab7 = st.tabs([
    "Constraint - sorted cpnodes",
    "Source/Sink - short/long constraints",
    "CPNode - short/long constraints",
    "Outages",
    "Auction Binding Round Comparison",
    "Branch Rating Changes - DA/Auction Binding Constraints Branches",
    "Outage Round 1 vs Round 2"
])

# --------------------------------------------------------------------
# TAB 1
# --------------------------------------------------------------------
with tab1:
    st.subheader("Sensitivities for a selected constraint")
    st.caption(f"Current case: {case_sel}")

    with st.expander("OOS constraints (no SF)", expanded=False):
        if OOS.empty:
            st.info("No matching *_OOS_constraints.feather found for this case.")
        else:
            o = OOS.copy()
            o["Name"] = o["Name"].astype(str)
            if "MarginalCost" in o.columns:
                o["MarginalCost"] = pd.to_numeric(o["MarginalCost"], errors="coerce")
            else:
                o["MarginalCost"] = np.nan

            if "DA" in o.columns:
                if pd.api.types.is_bool_dtype(o["DA"]):
                    pass
                else:
                    o["DA"] = (
                        o["DA"]
                        .astype(str)
                        .str.strip()
                        .str.upper()
                        .map({"TRUE": True, "FALSE": False, "1": True, "0": False})
                    )
                o["DA"] = o["DA"].fillna(False).astype(bool)
            else:
                o["DA"] = False

            o["AbsMarginalCost"] = o["MarginalCost"].abs()
            o = o.sort_values("AbsMarginalCost", ascending=False).reset_index(drop=True)
            o["Rank"] = np.arange(1, len(o) + 1)
            o["Percentile"] = (1 - (o["Rank"] - 1) / max(len(o), 1)) * 100

            view = o[["Rank", "Percentile", "Name", "AbsMarginalCost", "DA"]]

            st.dataframe(
                view,
                use_container_width=True,
                height=220,
                hide_index=True,
                column_config={
                    "Rank": st.column_config.NumberColumn("Rank", width="small", format="%d"),
                    "Percentile": st.column_config.NumberColumn("Pct", format="%.1f", width="small"),
                    "Name": st.column_config.TextColumn("Constraint", width="large"),
                    "AbsMarginalCost": st.column_config.NumberColumn("|MarginalCost|", format="%.2f", width="medium"),
                    "DA": st.column_config.CheckboxColumn("DA", width="small"),
                },
            )

    cA, cC = st.columns([1.2, 1.6])
    with cA:
        mode = st.radio("Constraint set", ["DA", "Auction"], horizontal=True, key="tab1_set")
    with cC:
        thres = st.number_input("SF threshold", min_value=0.0, value=0.001, step=0.0005, format="%.4f", key="tab1_thres")

    rank_df = da_rank if mode == "DA" else auction_rank
    if rank_df.empty:
        st.warning(f"No constraints found for set: {mode}")
        st.stop()

    rank_view = rank_df[["Rank", "Percentile", "Name", "MarginalCost"]].copy()

    constraint_options = rank_view["Name"].tolist()
    c = st.selectbox(
        "Select constraint",
        options=constraint_options,
        index=0,
        key=f"tab1_constraint_dropdown_{mode}"
    )

    st.dataframe(
        rank_view,
        use_container_width=True,
        height=260,
        hide_index=True,
        column_config={
            "Rank": st.column_config.NumberColumn("Rank", width="small", format="%d"),
            "Percentile": st.column_config.NumberColumn("Pct", format="%.1f", width="small"),
            "Name": st.column_config.TextColumn("Constraint", width="large"),
            "MarginalCost": st.column_config.NumberColumn("MarginalCost", format="%.2f", width="medium"),
        },
    )

    rec = rank_df.loc[rank_df["Name"].eq(c)]
    if rec.empty:
        st.warning("Selected constraint not found in the ranked set.")
        st.stop()

    rec = rec.iloc[0]
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Rank", int(rec["Rank"]))
    k2.metric("Percentile", f"{rec['Percentile']:.1f}%")
    k3.metric("MarginalCost", f"{rec['MarginalCost']:.2f}" if pd.notna(rec["MarginalCost"]) else "NA")
    k4.metric("Set", mode)

    s = M[c].dropna().round(5)
    top_pos = (s[s > float(thres)].sort_values(ascending=False).rename("SF").reset_index())
    tail_neg = (s[s < -float(thres)].sort_values(ascending=True).rename("SF").reset_index())

    col1, col2 = st.columns([1, 1])

    with col1:
        src_type_filter = st.selectbox("Source Type filter", ["All"] + all_types, index=0, key="tab1_src_type")
        top_pos_show = top_pos.copy()
        if src_type_filter != "All":
            top_pos_show = top_pos_show[top_pos_show["Type"] == src_type_filter]
        st.markdown("**Source Side**")
        st.dataframe(top_pos_show[["PNODENAME", "Type", "SF"]], use_container_width=True, height=500, hide_index=True)

    with col2:
        sink_type_filter = st.selectbox("Sink Type filter", ["All"] + all_types, index=0, key="tab1_sink_type")
        tail_neg_show = tail_neg.copy()
        if sink_type_filter != "All":
            tail_neg_show = tail_neg_show[tail_neg_show["Type"] == sink_type_filter]
        st.markdown("**Sink Side**")
        st.dataframe(tail_neg_show[["PNODENAME", "Type", "SF"]], use_container_width=True, height=500, hide_index=True)

    st.markdown("---")
    st.subheader("Compare any two CPNodes on this constraint")

    x1, x2, x3, x4 = st.columns([1.2, 1.8, 1.2, 1.8])

    with x1:
        any1_type = st.selectbox("CPNode A Type", ["All"] + all_types, key="tab1_any1_type")
    with x2:
        opts1 = node_type_df.copy() if any1_type == "All" else node_type_df[node_type_df["Type"] == any1_type].copy()
        cpnode_a = st.selectbox("CPNode A", options=sorted(opts1["Label"].tolist()), key="tab1_cpnode_a")

    with x3:
        any2_type = st.selectbox("CPNode B Type", ["All"] + all_types, key="tab1_any2_type")
    with x4:
        opts2 = node_type_df.copy() if any2_type == "All" else node_type_df[node_type_df["Type"] == any2_type].copy()
        cpnode_b = st.selectbox("CPNode B", options=sorted(opts2["Label"].tolist()), key="tab1_cpnode_b")

    if cpnode_a and cpnode_b:
        idx_a = label_to_idx[cpnode_a]
        idx_b = label_to_idx[cpnode_b]

        sf_a = pd.to_numeric(M.loc[idx_a, c], errors="coerce")
        sf_b = pd.to_numeric(M.loc[idx_b, c], errors="coerce")
        sf_diff = sf_b - sf_a if pd.notna(sf_a) and pd.notna(sf_b) else np.nan

        m1, m2, m3 = st.columns(3)
        m1.metric("SF @ CPNode A", f"{sf_a:.5f}" if pd.notna(sf_a) else "NA")
        m2.metric("SF @ CPNode B", f"{sf_b:.5f}" if pd.notna(sf_b) else "NA")
        m3.metric("B - A", f"{sf_diff:.5f}" if pd.notna(sf_diff) else "NA")

        comp_df = pd.DataFrame({
            "CPNode": [idx_a[0], idx_b[0]],
            "Type": [idx_a[1], idx_b[1]],
            "SF": [sf_a, sf_b]
        })
        st.dataframe(comp_df, use_container_width=True, hide_index=True)

# --------------------------------------------------------------------
# TAB 2
# --------------------------------------------------------------------
with tab2:
    st.subheader("Source - Sink path: short/long constraints")
    st.caption(f"Current case: {case_sel}")

    col1, col2, col3 = st.columns([2, 2, 1])

    with col1:
        src_type = st.selectbox("Source Type", ["All"] + all_types, index=0, key="src_type")
        if src_type == "All":
            src_nodes = idx_df["PNODENAME"].unique().tolist()
        else:
            src_nodes = idx_df[idx_df["Type"] == src_type]["PNODENAME"].unique().tolist()
        src_node = st.selectbox("Source CPNode", sorted(src_nodes), index=0, key="src_node")

    with col2:
        sink_type = st.selectbox("Sink Type", ["All"] + all_types, index=0, key="sink_type")
        if sink_type == "All":
            sink_nodes = idx_df["PNODENAME"].unique().tolist()
        else:
            sink_nodes = idx_df[idx_df["Type"] == sink_type]["PNODENAME"].unique().tolist()
        sink_node = st.selectbox("Sink CPNode", sorted(sink_nodes), index=0, key="sink_node")

    if src_node and sink_node:
        try:
            if src_type == "All":
                src_idx_row = idx_df[idx_df["PNODENAME"] == src_node].iloc[0]
                src_idx = (src_idx_row["PNODENAME"], src_idx_row["Type"])
            else:
                src_idx = (src_node, src_type)

            if sink_type == "All":
                sink_idx_row = idx_df[idx_df["PNODENAME"] == sink_node].iloc[0]
                sink_idx = (sink_idx_row["PNODENAME"], sink_idx_row["Type"])
            else:
                sink_idx = (sink_node, sink_type)

            delta = (M.loc[sink_idx] - M.loc[src_idx]).dropna()

        except KeyError as e:
            st.error(f"Missing CPNode: {e}")
            st.stop()

        k = col3.slider("Rows per side", 10, num_constr, 50, step=10)

        short_df = (
            delta[delta >= 0]
            .sort_values(ascending=False)
            .head(k)
            .round(5)
            .rename("sink - source")
            .reset_index()
            .rename(columns={"index": "Constraint"})
        )
        short_df["Constraint"] = short_df["Constraint"].astype(str)
        short_df = short_df.merge(constraint_meta, on="Constraint", how="left")
        short_df = short_df[["Constraint", "Set", "Rank", "MarginalCost", "sink - source"]]

        long_df = (
            delta[delta <= 0]
            .sort_values(ascending=True)
            .head(k)
            .round(5)
            .rename("sink - source")
            .reset_index()
            .rename(columns={"index": "Constraint"})
        )
        long_df["Constraint"] = long_df["Constraint"].astype(str)
        long_df = long_df.merge(constraint_meta, on="Constraint", how="left")
        long_df = long_df[["Constraint", "Set", "Rank", "MarginalCost", "sink - source"]]

        st.markdown("**Short constraints (>0)**")
        st.dataframe(
            short_df,
            use_container_width=True,
            height=500,
            hide_index=True,
            column_config={
                "Constraint": st.column_config.TextColumn("Constraint", width="large"),
                "Set": st.column_config.TextColumn("Set", width="small"),
                "Rank": st.column_config.NumberColumn("Rank", width="small", format="%d"),
                "MarginalCost": st.column_config.NumberColumn("MarginalCost", format="%.2f", width="medium"),
                "sink - source": st.column_config.NumberColumn("sink - source", format="%.5f", width="medium"),
            }
        )

        st.markdown("---")
        st.markdown("**Long constraints (<0)**")
        st.dataframe(
            long_df,
            use_container_width=True,
            height=500,
            hide_index=True,
            column_config={
                "Constraint": st.column_config.TextColumn("Constraint", width="large"),
                "Set": st.column_config.TextColumn("Set", width="small"),
                "Rank": st.column_config.NumberColumn("Rank", width="small", format="%d"),
                "MarginalCost": st.column_config.NumberColumn("MarginalCost", format="%.2f", width="medium"),
                "sink - source": st.column_config.NumberColumn("sink - source", format="%.5f", width="medium"),
            }
        )

# --------------------------------------------------------------------
# TAB 3
# --------------------------------------------------------------------
with tab3:
    st.subheader("CPNode: short/long constraints")
    st.caption(f"Current case: {case_sel}")

    col1, col2 = st.columns([2, 1])

    with col1:
        sel_type3 = st.selectbox("CPNode Type", ["All"] + all_types, index=0, key="single_type")

        if sel_type3 == "All":
            node_options = idx_df["PNODENAME"].unique().tolist()
        else:
            node_options = idx_df[idx_df["Type"] == sel_type3]["PNODENAME"].unique().tolist()

        node = st.selectbox("CPNode", sorted(node_options), index=0, key="single_node")

    k3 = col2.slider("Rows per side", 10, num_constr, 50, step=10, key="k_single")

    try:
        if sel_type3 == "All":
            rec = idx_df[idx_df["PNODENAME"] == node].iloc[0]
            node_idx = (rec["PNODENAME"], rec["Type"])
        else:
            node_idx = (node, sel_type3)

        row = M.loc[node_idx].dropna()

    except KeyError as e:
        st.error(f"Missing CPNode: {e}")
        st.stop()

    node_short = (
        row[row >= 0]
        .sort_values(ascending=False)
        .head(k3)
        .round(5)
        .rename("SF")
        .reset_index()
        .rename(columns={"index": "Constraint"})
    )
    node_short["Constraint"] = node_short["Constraint"].astype(str)
    node_short = node_short.merge(constraint_meta, on="Constraint", how="left")
    node_short = node_short[["Constraint", "Set", "Rank", "MarginalCost", "SF"]]

    node_long = (
        row[row <= 0]
        .sort_values(ascending=True)
        .head(k3)
        .round(5)
        .rename("SF")
        .reset_index()
        .rename(columns={"index": "Constraint"})
    )
    node_long["Constraint"] = node_long["Constraint"].astype(str)
    node_long = node_long.merge(constraint_meta, on="Constraint", how="left")
    node_long = node_long[["Constraint", "Set", "Rank", "MarginalCost", "SF"]]

    st.markdown(f"**Short constraints (sens>0)** - CPNode: `{node}`")
    st.dataframe(
        node_short,
        use_container_width=True,
        height=420,
        hide_index=True,
        column_config={
            "Constraint": st.column_config.TextColumn("Constraint", width="large"),
            "Set": st.column_config.TextColumn("Set", width="small"),
            "Rank": st.column_config.NumberColumn("Rank", width="small", format="%d"),
            "MarginalCost": st.column_config.NumberColumn("MarginalCost", format="%.2f", width="medium"),
            "SF": st.column_config.NumberColumn("SF", format="%.5f", width="medium"),
        }
    )

    st.markdown("---")
    st.markdown(f"**Long constraints (sens<0)** - CPNode: `{node}`")
    st.dataframe(
        node_long,
        use_container_width=True,
        height=420,
        hide_index=True,
        column_config={
            "Constraint": st.column_config.TextColumn("Constraint", width="large"),
            "Set": st.column_config.TextColumn("Set", width="small"),
            "Rank": st.column_config.NumberColumn("Rank", width="small", format="%d"),
            "MarginalCost": st.column_config.NumberColumn("MarginalCost", format="%.2f", width="medium"),
            "SF": st.column_config.NumberColumn("SF", format="%.5f", width="medium"),
        }
    )

# --------------------------------------------------------------------
# TAB 4
# --------------------------------------------------------------------
with tab4:
    st.subheader("Applied Outages")
    st.caption(f"Current case: {case_sel}")

    display_cols = [
        "EMSName", "FromBusName", "ToBusName", "maxKV", "FromArea", "ToArea",
        "Duration", "Status", "FromBusNum", "PRIORITY", "StartDate", "EndDate"
    ]

    outage_files = sorted([f for f in all_files if f.endswith("_outages.feather")])
    outage_windows = [parse_outage_window(f) for f in outage_files]
    outage_windows = [x for x in outage_windows if x is not None]
    outage_windows = sorted(outage_windows, key=lambda x: (x["win_start"], x["win_end"]))

    current_outage_file = f"{case_sel}_outages.feather"
    current_idx = None
    for i, rec in enumerate(outage_windows):
        if rec["file"] == current_outage_file:
            current_idx = i
            break

    prev_file = outage_windows[current_idx - 1]["file"] if current_idx is not None and current_idx > 0 else None
    next_file = outage_windows[current_idx + 1]["file"] if current_idx is not None and current_idx < len(outage_windows) - 1 else None

    if os.path.exists(outage_path):
        st.markdown(f"### Outage List - `{os.path.basename(outage_path)}`")

        try:
            outage_df = prepare_outage_df(load_feather(outage_path))

            prev_ems = set()
            next_ems = set()

            if prev_file is not None:
                prev_df = prepare_outage_df(load_feather(os.path.join(input_path, prev_file)))
                prev_ems = outage_ems_set(prev_df)

            if next_file is not None:
                next_df = prepare_outage_df(load_feather(os.path.join(input_path, next_file)))
                next_ems = outage_ems_set(next_df)

            outage_df["NewInCurrent"] = ~outage_df["EMSName"].isin(prev_ems) if prev_file is not None else False
            outage_df["DisappearNext"] = ~outage_df["EMSName"].isin(next_ems) if next_file is not None else False

            show_cols = [c for c in display_cols if c in outage_df.columns]

            info1, info2, info3 = st.columns(3)
            with info1:
                st.caption(f"Previous window: {prev_file if prev_file else 'None'}")
            with info2:
                st.caption(f"Current window: {current_outage_file}")
            with info3:
                st.caption(f"Next window: {next_file if next_file else 'None'}")

            def highlight_outage_rows(row):
                row_idx = row.name
                if bool(outage_df.loc[row_idx, "NewInCurrent"]):
                    return ["background-color: #ffcccc"] * len(row)
                if bool(outage_df.loc[row_idx, "DisappearNext"]):
                    return ["background-color: #d9f2d9"] * len(row)
                return [""] * len(row)

            styled_df = outage_df[show_cols].copy().style.apply(
                highlight_outage_rows,
                axis=1
            )

            st.dataframe(
                styled_df,
                use_container_width=True,
                height=800,
                hide_index=True,
                column_config={
                    "maxKV": st.column_config.NumberColumn("maxKV", format="%.1f", width="small"),
                    "Duration": st.column_config.NumberColumn("Duration", format="%d", width="small"),
                }
            )

        except Exception as e:
            st.error(f"Error loading outage file: {e}")
    else:
        st.warning(f"No outage file found for selected case: {case_sel}")

# --------------------------------------------------------------------
# TAB 5
# --------------------------------------------------------------------
with tab5:
    st.subheader("Auction binding constraints - round comparison")
    st.caption(f"Selected TOU: {tou_name}")
    auction_compare_path = os.path.join(
        input_path,
        f"{tou_name}_auction_round_comparison.feather"
    )
    if not os.path.exists(auction_compare_path):
        st.info(
            f"Auction round comparison feather not found: "
            f"{os.path.basename(auction_compare_path)}"
        )
    else:
        try:
            auction_cmp = load_auction_round_comparison(auction_compare_path).copy()
            if auction_cmp.empty:
                st.info("Auction round comparison file is empty.")
            else:
                status_options = sorted(
                    auction_cmp["Status"].dropna().astype(str).unique().tolist()
                ) if "Status" in auction_cmp.columns else []
                selected_status = st.multiselect(
                    "Status filter",
                    options=status_options,
                    default=status_options,
                    key="tab5_auction_status_filter"
                )
                show_only_changed = st.checkbox(
                    "Show only changed / new / missing constraints",
                    value=True,
                    key="tab5_auction_only_changed"
                )
                view = auction_cmp.copy()
                if selected_status and "Status" in view.columns:
                    view = view[view["Status"].isin(selected_status)]
                if show_only_changed and "AbsMarginalCostChange" in view.columns:
                    view = view[view["AbsMarginalCostChange"].fillna(0) > 0]
                shadow_cols = [
                    c for c in view.columns
                    if c.startswith("Round_") and c.endswith("_ShadowPrice")
                ]
                display_cols = [
                    "Compare",
                    "Status",
                    "DeviceName",
                    "DeviceType",
                    "Direction",
                    "Contingency",
                    "Class",
                ] + shadow_cols + [
                    "ShadowPriceChange",
                    "AbsMarginalCostChange",
                ]
                display_cols = [c for c in display_cols if c in view.columns]
                def highlight_auction_round_rows(row):
                    status = str(row.get("Status", ""))
                    if "New" in status:
                        return ["background-color: #ffcccc"] * len(row)
                    if "Missing" in status:
                        return ["background-color: #d9f2d9"] * len(row)
                    return [""] * len(row)
                styled_view = view[display_cols].style.apply(
                    highlight_auction_round_rows,
                    axis=1
                )
                st.dataframe(
                    styled_view,
                    use_container_width=True,
                    height=800,
                    hide_index=True,
                    column_config={
                        "Status": st.column_config.TextColumn("Status", width="medium"),
                        "DeviceName": st.column_config.TextColumn("DeviceName", width="large"),
                        "DeviceType": st.column_config.TextColumn("DeviceType", width="small"),
                        "Direction": st.column_config.TextColumn("Direction", width="small"),
                        "Contingency": st.column_config.TextColumn("Contingency", width="medium"),
                        "ShadowPriceChange": st.column_config.NumberColumn(
                            "MarginalCost Change",
                            format="%.2f",
                            width="medium"
                        ),
                        "AbsMarginalCostChange": st.column_config.NumberColumn(
                            "|Change|",
                            format="%.2f",
                            width="medium"
                        ),
                    }
                )
        except Exception as e:
            st.error(f"Error loading auction round comparison file: {e}")

# --------------------------------------------------------------------
# TAB 6
# --------------------------------------------------------------------
with tab6:
    st.subheader("Branch rating changes - compare any models")

    rating_path = os.path.join(input_path, "DA_Auction_constraints_rating_changes.feather")

    if not os.path.exists(rating_path):
        st.info("DA_Auction_constraints_rating_changes.feather not found.")
    else:
        df = load_feather(rating_path).copy()

        # normalize numeric columns
        df["Rating1"] = pd.to_numeric(df["Rating1"], errors="coerce")
        df["Rating2"] = pd.to_numeric(df["Rating2"], errors="coerce")

        if "FromBusNum" in df.columns:
            df["FromBusNum"] = pd.to_numeric(df["FromBusNum"], errors="coerce").round().astype("Int64")

        if "maxKV" in df.columns:
            df["maxKV"] = pd.to_numeric(df["maxKV"], errors="coerce").round(1)

        # columns to keep as line info
        line_info_cols = ["EMSName", "FromArea", "ToArea", "maxKV", "FromBusNum"]
        line_info_cols = [c for c in line_info_cols if c in df.columns]

        keys = ["EMSName"]

        models_all = df["Model"].dropna().astype(str).unique().tolist()

        models = st.multiselect(
            "Select models to compare",
            options=models_all,
            default=models_all[:4],
            key="tab5_models_any"
        )

        show_only_changed = st.checkbox(
            "Show only rows that change across selected models",
            value=True,
            key="tab5_onlychg"
        )

        if not models:
            st.info("Select at least one model.")
        else:
            sub = df[df["Model"].isin(models)].copy()

            # line info, one row per EMSName
            info_df = (
                sub[line_info_cols]
                .drop_duplicates(subset=["EMSName"])
                .copy()
            )

            wide = sub.pivot_table(
                index=keys,
                columns="Model",
                values=["Rating1", "Rating2"],
                aggfunc="first"
            )

            wide.columns = [f"{a}_{b}" for a, b in wide.columns]
            wide = wide.reset_index()

            r1_cols = [f"Rating1_{m}" for m in models if f"Rating1_{m}" in wide.columns]
            r2_cols = [f"Rating2_{m}" for m in models if f"Rating2_{m}" in wide.columns]

            if show_only_changed:
                r1_var = wide[r1_cols].nunique(dropna=True, axis=1) if r1_cols else 1
                r2_var = wide[r2_cols].nunique(dropna=True, axis=1) if r2_cols else 1
                wide = wide[(r1_var > 1) | (r2_var > 1)]

            if r1_cols:
                wide["Rating1_range"] = wide[r1_cols].max(axis=1) - wide[r1_cols].min(axis=1)
            if r2_cols:
                wide["Rating2_range"] = wide[r2_cols].max(axis=1) - wide[r2_cols].min(axis=1)

            # merge line info back
            wide = wide.merge(info_df, on="EMSName", how="left")

            cols = (
                ["EMSName"] +
                [c for c in ["FromArea", "ToArea", "maxKV", "FromBusNum"] if c in wide.columns] +
                r1_cols + r2_cols +
                [c for c in ["Rating1_range", "Rating2_range"] if c in wide.columns]
            )

            st.dataframe(
                wide[cols],
                use_container_width=True,
                height=700,
                hide_index=True,
                column_config={
                    "maxKV": st.column_config.NumberColumn("maxKV", format="%.1f", width="small"),
                    "FromBusNum": st.column_config.NumberColumn("FromBusNum", format="%d", width="small"),
                }
            )

# --------------------------------------------------------------------
# TAB 7
# --------------------------------------------------------------------
with tab7:
    st.subheader("Outage comparison - Round 1 vs Round 2")
    st.caption(f"Current case: {case_sel}")

    current_outage_file = f"{case_sel}_outages.feather"
    round1_outage_path = os.path.join(round1_input_path, current_outage_file)
    round2_outage_path = outage_path

    st.caption(f"Round 1 file: {round1_outage_path}")
    st.caption(f"Round 2 file: {round2_outage_path}")

    display_cols = [
        "RoundComparison", "EMSName", "FromBusName", "ToBusName", "maxKV",
        "FromArea", "ToArea", "Duration", "Status", "FromBusNum", "PRIORITY",
        "StartDate", "EndDate"
    ]

    if not os.path.exists(round1_input_path):
        st.info(f"Round 1 feathers folder not found: {round1_input_path}")
    elif not os.path.exists(round1_outage_path):
        st.info(f"Round 1 outage file not found: {os.path.basename(round1_outage_path)}")
    elif not os.path.exists(round2_outage_path):
        st.info(f"Round 2 outage file not found: {os.path.basename(round2_outage_path)}")
    else:
        try:
            r1_df = prepare_outage_df(load_feather(round1_outage_path))
            r2_df = prepare_outage_df(load_feather(round2_outage_path))

            r1_ems = outage_ems_set(r1_df)
            r2_ems = outage_ems_set(r2_df)

            new_in_round2 = r2_ems - r1_ems
            missing_in_round2 = r1_ems - r2_ems
            unchanged = r2_ems & r1_ems

            a, b, c = st.columns(3)
            a.metric("New in Round 2", len(new_in_round2))
            b.metric("Missing in Round 2", len(missing_in_round2))
            c.metric("In both rounds", len(unchanged))

            show_only_changed_rounds = st.checkbox(
                "Show only new or missing outages",
                value=True,
                key="tab7_only_changed"
            )

            r2_view = r2_df.copy()
            r2_view["RoundComparison"] = np.where(
                r2_view["EMSName"].isin(new_in_round2),
                "New in Round 2",
                "In both rounds"
            )

            missing_view = r1_df[r1_df["EMSName"].isin(missing_in_round2)].copy()
            missing_view["RoundComparison"] = "Missing in Round 2"

            if show_only_changed_rounds:
                compare_df = pd.concat([
                    r2_view[r2_view["RoundComparison"].eq("New in Round 2")],
                    missing_view
                ], ignore_index=True)
            else:
                compare_df = pd.concat([r2_view, missing_view], ignore_index=True)

            compare_df = compare_df.sort_values(
                ["RoundComparison", "EMSName"],
                ascending=[True, True]
            ).reset_index(drop=True)

            show_cols = [c for c in display_cols if c in compare_df.columns]

            def highlight_round_outage_rows(row):
                status = str(row.get("RoundComparison", ""))
                if status == "New in Round 2":
                    return ["background-color: #ffcccc"] * len(row)
                if status == "Missing in Round 2":
                    return ["background-color: #d9f2d9"] * len(row)
                return [""] * len(row)

            styled_compare = compare_df[show_cols].style.apply(
                highlight_round_outage_rows,
                axis=1
            )

            st.dataframe(
                styled_compare,
                use_container_width=True,
                height=800,
                hide_index=True,
                column_config={
                    "RoundComparison": st.column_config.TextColumn("Round Comparison", width="medium"),
                    "maxKV": st.column_config.NumberColumn("maxKV", format="%.1f", width="small"),
                    "Duration": st.column_config.NumberColumn("Duration", format="%d", width="small"),
                    "FromBusNum": st.column_config.NumberColumn("FromBusNum", format="%d", width="small"),
                }
            )

        except Exception as e:
            st.error(f"Error comparing Round 1 and Round 2 outage files: {e}")
