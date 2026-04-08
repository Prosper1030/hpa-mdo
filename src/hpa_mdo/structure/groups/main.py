"""Top-level structural group assembly and problem entry points."""
from __future__ import annotations

import numpy as np
import openmdao.api as om

from hpa_mdo.core.logging import get_logger
from hpa_mdo.structure.buckling import BucklingComp
from hpa_mdo.structure.components.constraints import (
    KSFailureComp,
    StructuralMassComp,
    TipDeflectionConstraintComp,
    TwistConstraintComp,
    VonMisesStressComp,
)
from hpa_mdo.structure.components.loads import ExternalLoadsComp
from hpa_mdo.structure.components.spar_props import (
    DualSparPropertiesComp,
    SegmentToElementComp,
)
from hpa_mdo.structure.fem.assembly import SpatialBeamFEM
from hpa_mdo.structure.groups.load_case import StructuralLoadCaseGroup
from hpa_mdo.structure.spar_model import segment_boundaries_from_lengths

logger = get_logger(__name__)


def _is_single_mapped_load(aero_loads: dict) -> bool:
    """Return True when ``aero_loads`` looks like a single mapped load dict."""
    return isinstance(aero_loads, dict) and "lift_per_span" in aero_loads


def _normalise_load_case_inputs(cfg, aero_loads: dict) -> dict[str, tuple[object, dict]]:
    """Return ``{case_name: (load_case_cfg, mapped_loads)}`` with backward compatibility."""
    from hpa_mdo.core.config import LoadCaseConfig

    if _is_single_mapped_load(aero_loads):
        if len(cfg.flight.cases) > 1:
            raise ValueError(
                "cfg.flight.cases declares multiple load cases, but aero_loads contains only one case."
            )
        default_case = cfg.structural_load_cases()[0]
        return {default_case.name: (default_case, aero_loads)}

    if not isinstance(aero_loads, dict):
        raise TypeError("aero_loads must be a mapped-load dict or {case_name: mapped_loads}.")

    explicit_cases = {case.name: case for case in cfg.flight.cases}
    case_entries: dict[str, tuple[object, dict]] = {}

    for case_name, case_loads in aero_loads.items():
        if not _is_single_mapped_load(case_loads):
            raise ValueError(
                f"aero_loads['{case_name}'] must be a mapped load dict with 'lift_per_span'."
            )

        load_case = explicit_cases.get(case_name)
        if load_case is None:
            load_case = LoadCaseConfig(
                name=case_name,
                velocity=cfg.flight.velocity,
                air_density=cfg.flight.air_density,
            )

        case_entries[case_name] = (load_case, case_loads)

    if explicit_cases:
        missing = sorted(set(explicit_cases) - set(case_entries))
        extra = sorted(set(case_entries) - set(explicit_cases))
        if missing or extra:
            details = []
            if missing:
                details.append(f"missing load cases: {', '.join(missing)}")
            if extra:
                details.append(f"unexpected load cases: {', '.join(extra)}")
            raise ValueError("; ".join(details))

    return case_entries


class HPAStructuralGroup(om.Group):
    """Complete structural analysis group for HPA wing spar optimization.

    Subsystems:
        seg_mapper → spar_props → ext_loads → fem → stress → buckling
        → failure, mass, twist
    """

    def initialize(self):
        self.options.declare("cfg", desc="HPAConfig object")
        self.options.declare("aircraft", desc="Aircraft object")
        self.options.declare("aero_loads", desc="Dict from LoadMapper.map_loads()")
        self.options.declare("materials_db", desc="MaterialDB")

    def setup(self):
        from hpa_mdo.core.config import HPAConfig
        cfg: HPAConfig = self.options["cfg"]
        ac = self.options["aircraft"]
        aero = self.options["aero_loads"]
        mat_db = self.options["materials_db"]

        wing = ac.wing
        nn = wing.n_stations
        ne = nn - 1
        y = wing.y
        dy = np.diff(y)

        # Materials
        mat_main = mat_db.get(cfg.main_spar.material)
        mat_rear = mat_db.get(cfg.rear_spar.material)
        rear_on = cfg.rear_spar.enabled

        # Segment boundaries
        seg_lengths = cfg.spar_segment_lengths(cfg.main_spar)
        seg_bounds = segment_boundaries_from_lengths(seg_lengths)
        n_seg = len(seg_lengths)

        # Element centres (midpoint of each element)
        elem_centres = (y[:-1] + y[1:]) / 2.0

        # Node spacings (tributary length per node for load distribution)
        node_spacings = np.zeros(nn)
        node_spacings[0] = dy[0] / 2.0
        node_spacings[-1] = dy[-1] / 2.0
        for i in range(1, nn - 1):
            node_spacings[i] = (dy[i-1] + dy[i]) / 2.0

        # Outer radii (constant — from airfoil geometry)
        R_main_nodes = compute_outer_radius_from_wing(wing, cfg.main_spar)
        R_rear_nodes = compute_outer_radius_from_wing(wing, cfg.rear_spar) if rear_on else np.zeros(nn)
        # Element-averaged outer radii
        R_main_elem = (R_main_nodes[:-1] + R_main_nodes[1:]) / 2.0
        R_rear_elem = (R_rear_nodes[:-1] + R_rear_nodes[1:]) / 2.0

        # Z-offsets and spar separation per element
        z_main_elem = (wing.main_spar_z_camber[:-1] + wing.main_spar_z_camber[1:]) / 2.0
        z_rear_elem = (wing.rear_spar_z_camber[:-1] + wing.rear_spar_z_camber[1:]) / 2.0
        chord_elem = (wing.chord[:-1] + wing.chord[1:]) / 2.0
        d_chord_elem = (wing.rear_spar_xc - wing.main_spar_xc) * chord_elem

        case_entries = _normalise_load_case_inputs(cfg, aero)
        self._case_names = tuple(case_entries)
        self._multi_case = len(case_entries) > 1

        # Lift wire nodes
        lw_node_indices = None
        if cfg.lift_wires.enabled and cfg.lift_wires.attachments:
            lw_node_indices = []
            for att in cfg.lift_wires.attachments:
                idx = int(np.argmin(np.abs(y - att.y)))
                lw_node_indices.append(idx)

        # FEM nodes (3D coordinates)
        # Y along span, Z from dihedral, X at spar location
        nodes_3d = np.zeros((nn, 3))
        nodes_3d[:, 1] = y  # spanwise
        # Dihedral offset
        dih_rad = np.deg2rad(wing.dihedral_deg)
        z_dihedral = np.zeros(nn)
        for i in range(1, nn):
            z_dihedral[i] = z_dihedral[i-1] + dy[i-1] * np.tan(dih_rad[i])
        nodes_3d[:, 2] = z_dihedral
        nodes_3d[:, 0] = wing.main_spar_xc * wing.chord  # chordwise position

        # Joint mass
        n_main_joints = len(cfg.joint_positions(seg_lengths))
        n_rear_joints = len(cfg.joint_positions(
            cfg.spar_segment_lengths(cfg.rear_spar))) if rear_on else 0
        joint_mass_half = (
            n_main_joints * cfg.main_spar.joint_mass_kg
            + n_rear_joints * cfg.rear_spar.joint_mass_kg
        )

        # Allowable stress = UTS / material_safety_factor
        sigma_allow_main = mat_main.tensile_strength / cfg.safety.material_safety_factor
        sigma_allow_rear = mat_rear.tensile_strength / cfg.safety.material_safety_factor

        # ── Build subsystems ──

        # 1. Segment mapper
        self.add_subsystem("seg_mapper", SegmentToElementComp(
            n_segments=n_seg,
            n_elements=ne,
            segment_boundaries=seg_bounds,
            element_centres=elem_centres,
            rear_enabled=rear_on,
        ))

        # 2. Dual spar properties
        self.add_subsystem("spar_props", DualSparPropertiesComp(
            n_elements=ne,
            z_main=z_main_elem,
            z_rear=z_rear_elem,
            d_chord=d_chord_elem,
            E_main=mat_main.E,
            G_main=mat_main.G,
            rho_main=mat_main.density,
            E_rear=mat_rear.E,
            G_rear=mat_rear.G,
            rho_rear=mat_rear.density,
            rear_enabled=rear_on,
            warping_knockdown=cfg.safety.dual_spar_warping_knockdown,
        ))

        E_avg = (mat_main.E + mat_rear.E) / 2.0 if rear_on else mat_main.E
        G_avg = (mat_main.G + mat_rear.G) / 2.0 if rear_on else mat_main.G

        # Set node coordinates as fixed input
        indeps = self.add_subsystem("indeps", om.IndepVarComp())
        indeps.add_output("nodes", val=nodes_3d, units="m")

        # Store initial element radii for use in build_structural_problem()
        self._R_main_elem_init = R_main_elem
        self._R_rear_elem_init = R_rear_elem if rear_on else None

        # 8. Structural mass
        self.add_subsystem("mass", StructuralMassComp(
            n_elements=ne,
            element_lengths=dy,
            joint_mass_total=joint_mass_half,
        ))

        if len(case_entries) == 1:
            load_case, case_loads = next(iter(case_entries.values()))
            aero_scale = load_case.aero_scale
            lift = np.asarray(case_loads["lift_per_span"]) * aero_scale
            torque = np.asarray(case_loads.get("torque_per_span", np.zeros(nn))) * aero_scale

            # 3. External loads
            self.add_subsystem("ext_loads", ExternalLoadsComp(
                n_nodes=nn,
                lift_per_span=lift,
                torque_per_span=torque,
                node_spacings=node_spacings,
                element_lengths=dy,
                gravity_scale=load_case.gravity_scale,
            ))

            # 4. FEM solver
            self.add_subsystem("fem", SpatialBeamFEM(
                n_nodes=nn,
                E_avg=E_avg,
                G_avg=G_avg,
                fixed_node=0,
                lift_wire_nodes=lw_node_indices,
                max_matrix_entry=cfg.solver.fem_max_matrix_entry,
                max_disp_entry=cfg.solver.fem_max_disp_entry,
                bc_penalty=cfg.solver.fem_bc_penalty,
            ))

            # 5. Stress computation
            self.add_subsystem("stress", VonMisesStressComp(
                n_nodes=nn,
                E_main=mat_main.E,
                E_rear=mat_rear.E,
                G_main=mat_main.G,
                G_rear=mat_rear.G,
                z_main=z_main_elem,
                z_rear=z_rear_elem,
                rear_enabled=rear_on,
            ))

            # 6. Shell buckling
            self.add_subsystem("buckling", BucklingComp(
                n_nodes=nn,
                E_main=mat_main.E,
                E_rear=mat_rear.E if rear_on else 0.0,
                z_main=z_main_elem,
                z_rear=z_rear_elem,
                rear_enabled=rear_on,
                knockdown_factor=cfg.safety.shell_buckling_knockdown,
                bending_enhancement=cfg.safety.shell_buckling_bending_enhancement,
                ks_rho=cfg.safety.ks_rho_buckling,
            ))

            # 7. KS failure
            self.add_subsystem("failure", KSFailureComp(
                n_elements=ne,
                sigma_allow_main=sigma_allow_main,
                sigma_allow_rear=sigma_allow_rear,
                rear_enabled=rear_on,
                rho_ks=cfg.safety.ks_rho_stress,
            ))

            # 9. Twist constraint
            self.add_subsystem(
                "twist",
                TwistConstraintComp(n_nodes=nn, ks_rho=cfg.safety.ks_rho_twist),
            )

            # 10. Tip deflection constraint
            self.add_subsystem("tip_defl", TipDeflectionConstraintComp(n_nodes=nn))
        else:
            for case_name, (load_case, case_loads) in case_entries.items():
                lift = case_loads["lift_per_span"]
                torque = case_loads.get("torque_per_span", np.zeros(nn))
                case_group_name = f"case_{case_name}"

                self.add_subsystem(
                    case_group_name,
                    StructuralLoadCaseGroup(
                        load_case=load_case,
                        n_nodes=nn,
                        lift_per_span=lift,
                        torque_per_span=torque,
                        node_spacings=node_spacings,
                        element_lengths=dy,
                        E_avg=E_avg,
                        G_avg=G_avg,
                        E_main=mat_main.E,
                        E_rear=mat_rear.E,
                        G_main=mat_main.G,
                        G_rear=mat_rear.G,
                        z_main=z_main_elem,
                        z_rear=z_rear_elem,
                        sigma_allow_main=sigma_allow_main,
                        sigma_allow_rear=sigma_allow_rear,
                        rear_enabled=rear_on,
                        fixed_node=0,
                        lift_wire_nodes=lw_node_indices,
                        shell_buckling_knockdown=cfg.safety.shell_buckling_knockdown,
                        shell_buckling_bending_enhancement=cfg.safety.shell_buckling_bending_enhancement,
                        ks_rho_stress=cfg.safety.ks_rho_stress,
                        ks_rho_buckling=cfg.safety.ks_rho_buckling,
                        ks_rho_twist=cfg.safety.ks_rho_twist,
                        fem_max_matrix_entry=cfg.solver.fem_max_matrix_entry,
                        fem_max_disp_entry=cfg.solver.fem_max_disp_entry,
                        fem_bc_penalty=cfg.solver.fem_bc_penalty,
                    ),
                )

        # ── Connections ──
        self.connect("seg_mapper.main_t_elem", "spar_props.main_t_elem")
        self.connect("seg_mapper.main_r_elem", "spar_props.main_r_elem")
        if rear_on:
            self.connect("seg_mapper.rear_t_elem", "spar_props.rear_t_elem")
            self.connect("seg_mapper.rear_r_elem", "spar_props.rear_r_elem")

        self.connect("spar_props.mass_per_length", "mass.mass_per_length")
        if len(case_entries) == 1:
            self.connect("spar_props.mass_per_length", "ext_loads.mass_per_length")

            self.connect("indeps.nodes", "fem.nodes")
            self.connect("spar_props.EI_flap", "fem.EI_flap")
            self.connect("spar_props.GJ", "fem.GJ")
            self.connect("spar_props.A_equiv", "fem.A_equiv")
            self.connect("spar_props.Iy_equiv", "fem.Iy_equiv")
            self.connect("spar_props.Iz_equiv", "fem.Iz_equiv")
            self.connect("spar_props.J_equiv", "fem.J_equiv")
            self.connect("ext_loads.loads", "fem.loads")

            self.connect("fem.disp", "stress.disp")
            self.connect("indeps.nodes", "stress.nodes")
            self.connect("seg_mapper.main_r_elem", "stress.R_main_elem")
            self.connect("seg_mapper.main_t_elem", "stress.main_t_elem")
            self.connect("spar_props.I_main", "stress.I_main")
            self.connect("spar_props.EI_flap", "stress.EI_flap")
            self.connect("spar_props.GJ", "stress.GJ")
            if rear_on:
                self.connect("seg_mapper.rear_r_elem", "stress.R_rear_elem")
                self.connect("seg_mapper.rear_t_elem", "stress.rear_t_elem")
                self.connect("spar_props.I_rear", "stress.I_rear")

            self.connect("fem.disp", "buckling.disp")
            self.connect("indeps.nodes", "buckling.nodes")
            self.connect("seg_mapper.main_r_elem", "buckling.main_r_elem")
            self.connect("seg_mapper.main_t_elem", "buckling.main_t_elem")
            if rear_on:
                self.connect("seg_mapper.rear_r_elem", "buckling.rear_r_elem")
                self.connect("seg_mapper.rear_t_elem", "buckling.rear_t_elem")

            self.connect("stress.vonmises_main", "failure.vonmises_main")
            if rear_on:
                self.connect("stress.vonmises_rear", "failure.vonmises_rear")

            self.connect("fem.disp", "twist.disp")
            self.connect("indeps.nodes", "twist.nodes")
            self.connect("fem.disp", "tip_defl.disp")
        else:
            for case_name in case_entries:
                case_group_name = f"case_{case_name}"
                self.connect("spar_props.mass_per_length", f"{case_group_name}.mass_per_length")
                self.connect("indeps.nodes", f"{case_group_name}.nodes")
                self.connect("spar_props.EI_flap", f"{case_group_name}.EI_flap")
                self.connect("spar_props.GJ", f"{case_group_name}.GJ")
                self.connect("spar_props.A_equiv", f"{case_group_name}.A_equiv")
                self.connect("spar_props.Iy_equiv", f"{case_group_name}.Iy_equiv")
                self.connect("spar_props.Iz_equiv", f"{case_group_name}.Iz_equiv")
                self.connect("spar_props.J_equiv", f"{case_group_name}.J_equiv")
                self.connect("seg_mapper.main_r_elem", f"{case_group_name}.R_main_elem")
                self.connect("seg_mapper.main_t_elem", f"{case_group_name}.main_t_elem")
                self.connect("spar_props.I_main", f"{case_group_name}.I_main")
                if rear_on:
                    self.connect("seg_mapper.rear_r_elem", f"{case_group_name}.R_rear_elem")
                    self.connect("seg_mapper.rear_t_elem", f"{case_group_name}.rear_t_elem")
                    self.connect("spar_props.I_rear", f"{case_group_name}.I_rear")


def compute_outer_radius_from_wing(wing, spar_cfg) -> np.ndarray:
    """Compute outer tube radius at each wing station."""
    from hpa_mdo.structure.spar_model import compute_outer_radius
    return compute_outer_radius(
        wing.y, wing.chord, wing.airfoil_thickness, spar_cfg)


def build_structural_problem(
    cfg,
    aircraft,
    aero_loads: dict,
    materials_db,
    force_alloc_complex: bool = False,
) -> om.Problem:
    """Build the OpenMDAO structural optimization problem.

    Parameters
    ----------
    cfg : HPAConfig
    aircraft : Aircraft
    aero_loads : dict from LoadMapper.map_loads()
    materials_db : MaterialDB
    force_alloc_complex : bool, optional
        Forwarded to ``Problem.setup()`` so tests can run complex-step total
        derivative checks through the assembled structural model.

    Returns
    -------
    prob : om.Problem (setup but not run)
    """
    case_entries = _normalise_load_case_inputs(cfg, aero_loads)
    prob = om.Problem()
    model = prob.model

    seg_lengths = cfg.spar_segment_lengths(cfg.main_spar)
    n_seg = len(seg_lengths)
    n_elem = aircraft.wing.n_stations - 1
    rear_on = cfg.rear_spar.enabled
    logger.debug(
        "Building structural problem (n_seg=%d, rear_on=%s).",
        n_seg,
        rear_on,
    )

    # Add the structural group
    struct_group = HPAStructuralGroup(
        cfg=cfg,
        aircraft=aircraft,
        aero_loads=aero_loads,
        materials_db=materials_db,
    )
    model.add_subsystem("struct", struct_group)

    # ── Design Variables ──
    solver_cfg = cfg.solver
    min_t = cfg.main_spar.min_wall_thickness
    max_t = solver_cfg.max_wall_thickness_m

    model.add_design_var(
        "struct.seg_mapper.main_t_seg",
        lower=min_t, upper=max_t,
        ref=0.002,  # scaling reference
    )

    model.add_design_var(
        "struct.seg_mapper.main_r_seg",
        lower=solver_cfg.min_radius_m, upper=solver_cfg.max_radius_m,
        ref=0.025,
    )

    if rear_on:
        min_t_r = cfg.rear_spar.min_wall_thickness
        model.add_design_var(
            "struct.seg_mapper.rear_t_seg",
            lower=min_t_r, upper=max_t,
            ref=0.002,
        )
        model.add_design_var(
            "struct.seg_mapper.rear_r_seg",
            lower=solver_cfg.min_radius_m, upper=solver_cfg.max_radius_m,
            ref=0.025,
        )

    # Thickness-to-radius geometric feasibility: t <= eta * R.
    ratio_limit = solver_cfg.max_thickness_to_radius_ratio
    model.add_subsystem(
        "main_thickness_ratio",
        om.ExecComp(
            "margin = eta * radius - thickness",
            margin={"shape": (n_seg,), "units": "m"},
            radius={"shape": (n_seg,), "units": "m"},
            thickness={"shape": (n_seg,), "units": "m"},
            eta=ratio_limit,
        ),
    )
    model.connect("struct.seg_mapper.main_r_seg", "main_thickness_ratio.radius")
    model.connect("struct.seg_mapper.main_t_seg", "main_thickness_ratio.thickness")
    model.add_constraint("main_thickness_ratio.margin", lower=0.0)

    if n_seg > 1:
        # Segment manufacturability: enforce monotonic taper on outer radius.
        # Prevent oscillating OD patterns that cannot be joined in practice.
        seg_idx_in = np.arange(n_seg - 1, dtype=int)
        seg_idx_out = np.arange(1, n_seg, dtype=int)
        model.add_subsystem(
            "main_radius_taper",
            om.ExecComp(
                "margin = r_in - r_out",
                margin={"shape": (n_seg - 1,), "units": "m"},
                r_in={"shape": (n_seg - 1,), "units": "m"},
                r_out={"shape": (n_seg - 1,), "units": "m"},
                has_diag_partials=True,
            ),
        )
        model.connect(
            "struct.seg_mapper.main_r_seg",
            "main_radius_taper.r_in",
            src_indices=seg_idx_in,
        )
        model.connect(
            "struct.seg_mapper.main_r_seg",
            "main_radius_taper.r_out",
            src_indices=seg_idx_out,
        )
        model.add_constraint("main_radius_taper.margin", lower=0.0)

    if rear_on:
        model.add_subsystem(
            "rear_thickness_ratio",
            om.ExecComp(
                "margin = eta * radius - thickness",
                margin={"shape": (n_seg,), "units": "m"},
                radius={"shape": (n_seg,), "units": "m"},
                thickness={"shape": (n_seg,), "units": "m"},
                eta=ratio_limit,
            ),
        )
        model.connect("struct.seg_mapper.rear_r_seg", "rear_thickness_ratio.radius")
        model.connect("struct.seg_mapper.rear_t_seg", "rear_thickness_ratio.thickness")
        model.add_constraint("rear_thickness_ratio.margin", lower=0.0)

        if n_seg > 1:
            model.add_subsystem(
                "rear_radius_taper",
                om.ExecComp(
                    "margin = r_in - r_out",
                    margin={"shape": (n_seg - 1,), "units": "m"},
                    r_in={"shape": (n_seg - 1,), "units": "m"},
                    r_out={"shape": (n_seg - 1,), "units": "m"},
                    has_diag_partials=True,
                ),
            )
            model.connect(
                "struct.seg_mapper.rear_r_seg",
                "rear_radius_taper.r_in",
                src_indices=np.arange(n_seg - 1, dtype=int),
            )
            model.connect(
                "struct.seg_mapper.rear_r_seg",
                "rear_radius_taper.r_out",
                src_indices=np.arange(1, n_seg, dtype=int),
            )
            model.add_constraint("rear_radius_taper.margin", lower=0.0)

        # Main spar dominance constraints:
        #   1) radius margin per segment
        #   2) EI margin per element
        dominance_margin = solver_cfg.main_spar_dominance_margin_m
        ei_ratio = solver_cfg.main_spar_ei_ratio

        model.add_subsystem(
            "main_rear_radius_dominance",
            om.ExecComp(
                "margin = main_r - rear_r",
                margin={"shape": (n_seg,), "units": "m"},
                main_r={"shape": (n_seg,), "units": "m"},
                rear_r={"shape": (n_seg,), "units": "m"},
                has_diag_partials=True,
            ),
        )
        model.connect("struct.seg_mapper.main_r_seg", "main_rear_radius_dominance.main_r")
        model.connect("struct.seg_mapper.rear_r_seg", "main_rear_radius_dominance.rear_r")
        model.add_constraint(
            "main_rear_radius_dominance.margin",
            lower=dominance_margin,
        )

        model.add_subsystem(
            "main_rear_ei_dominance",
            om.ExecComp(
                "margin = ei_main - ratio * ei_rear",
                margin={"shape": (n_elem,), "units": "N*m**2"},
                ei_main={"shape": (n_elem,), "units": "N*m**2"},
                ei_rear={"shape": (n_elem,), "units": "N*m**2"},
                ratio=ei_ratio,
                has_diag_partials=True,
            ),
        )
        model.connect("struct.spar_props.EI_main", "main_rear_ei_dominance.ei_main")
        model.connect("struct.spar_props.EI_rear", "main_rear_ei_dominance.ei_rear")
        model.add_constraint("main_rear_ei_dominance.margin", lower=0.0)

    # ── Objective: minimise total spar mass ──
    model.add_objective("struct.mass.total_mass_full", ref=10.0)

    # ── Constraints ──
    if len(case_entries) == 1:
        load_case, _ = next(iter(case_entries.values()))
        twist_limit = (
            load_case.max_twist_deg
            if load_case.max_twist_deg is not None
            else cfg.wing.max_tip_twist_deg
        )
        deflection_limit = (
            load_case.max_tip_deflection_m
            if load_case.max_tip_deflection_m is not None
            else cfg.wing.max_tip_deflection_m
        )

        # 1. Stress: KS(σ/σ_allow - 1) ≤ 0
        model.add_constraint("struct.failure.failure", upper=0.0)

        # 2. Shell buckling: KS(buckling_ratio - 1) ≤ 0
        model.add_constraint("struct.buckling.buckling_index", upper=0.0)

        # 3. Twist: |θ_max| ≤ max_tip_twist_deg
        model.add_constraint("struct.twist.twist_max_deg", upper=twist_limit)

        # 4. Tip deflection constraint
        if deflection_limit is not None:
            model.add_constraint(
                "struct.tip_defl.tip_deflection_m",
                upper=deflection_limit,
            )
    else:
        for case_name, (load_case, _) in case_entries.items():
            twist_limit = (
                load_case.max_twist_deg
                if load_case.max_twist_deg is not None
                else cfg.wing.max_tip_twist_deg
            )
            deflection_limit = (
                load_case.max_tip_deflection_m
                if load_case.max_tip_deflection_m is not None
                else cfg.wing.max_tip_deflection_m
            )
            case_path = f"struct.case_{case_name}"
            model.add_constraint(f"{case_path}.failure", upper=0.0)
            model.add_constraint(f"{case_path}.buckling_index", upper=0.0)
            model.add_constraint(f"{case_path}.twist_max_deg", upper=twist_limit)
            if deflection_limit is not None:
                model.add_constraint(
                    f"{case_path}.tip_deflection_m",
                    upper=deflection_limit,
                )

    # ── Driver ──
    driver = prob.driver = om.ScipyOptimizeDriver()
    driver.options["optimizer"] = cfg.solver.optimizer
    driver.options["tol"] = cfg.solver.optimizer_tol
    driver.options["maxiter"] = cfg.solver.optimizer_maxiter
    driver.options["disp"] = True

    # ── Recorder (optional) ──
    # prob.driver.add_recorder(om.SqliteRecorder("hpa_opt.sql"))

    prob.setup(force_alloc_complex=force_alloc_complex)

    # ── Initial values ──
    # Wall thickness: start with moderate value (2 mm)
    init_t = np.ones(n_seg) * 0.002
    prob.set_val("struct.seg_mapper.main_t_seg", init_t, units="m")
    if rear_on:
        prob.set_val("struct.seg_mapper.rear_t_seg", init_t * 0.7, units="m")

    # Outer radii: derive from wing geometry (element values averaged per segment)
    # The group stores these after setup — retrieve from the instantiated subsystem.
    wing = aircraft.wing
    seg_bounds = segment_boundaries_from_lengths(seg_lengths)
    nn = wing.n_stations
    y = wing.y
    elem_centres = (y[:-1] + y[1:]) / 2.0

    R_main_elem_init = struct_group._R_main_elem_init
    main_r_seg_init = _elem_to_seg_mean(R_main_elem_init, elem_centres, seg_bounds, n_seg)
    prob.set_val("struct.seg_mapper.main_r_seg", main_r_seg_init, units="m")

    if rear_on:
        R_rear_elem_init = struct_group._R_rear_elem_init
        rear_r_seg_init = _elem_to_seg_mean(R_rear_elem_init, elem_centres, seg_bounds, n_seg)
        prob.set_val("struct.seg_mapper.rear_r_seg", rear_r_seg_init, units="m")

    return prob


def _elem_to_seg_mean(
    elem_vals: np.ndarray,
    elem_centres: np.ndarray,
    seg_bounds: np.ndarray,
    n_seg: int,
) -> np.ndarray:
    """Average element values within each segment to produce per-segment values."""
    seg_vals = np.zeros(n_seg)
    for s in range(n_seg):
        mask = (elem_centres >= seg_bounds[s]) & (elem_centres < seg_bounds[s + 1])
        if np.any(mask):
            seg_vals[s] = np.mean(elem_vals[mask])
        else:
            # No elements in segment — fall back to nearest element
            dists = np.abs(elem_centres - 0.5 * (seg_bounds[s] + seg_bounds[s + 1]))
            seg_vals[s] = elem_vals[np.argmin(dists)]
    return seg_vals


def run_analysis(prob: om.Problem) -> dict:
    """Run a single analysis (no optimization) and return results."""
    logger.debug("Running structural analysis model.")
    prob.run_model()
    results = _extract_results(prob)
    logger.debug(
        "Structural analysis complete (mass=%.3f kg, failure=%.4f).",
        results["total_mass_full_kg"],
        results["failure"],
    )
    return results


def run_optimization(prob: om.Problem) -> dict:
    """Run the full optimization and return results."""
    logger.info("Running structural optimization driver.")
    prob.run_driver()
    results = _extract_results(prob)
    logger.info(
        "Structural optimization complete (mass=%.3f kg, failure=%.4f).",
        results["total_mass_full_kg"],
        results["failure"],
    )
    return results


def _extract_results(prob: om.Problem) -> dict:
    """Extract key results from solved problem."""
    def _get_scalar(name: str) -> float:
        return float(np.asarray(prob.get_val(name)).item())

    struct_group = prob.model.struct
    nn = struct_group.options["aircraft"].wing.n_stations
    rear_on = struct_group.options["cfg"].rear_spar.enabled
    case_names = tuple(getattr(struct_group, "_case_names", ("default",)))
    multi_case = bool(getattr(struct_group, "_multi_case", False))

    res = {
        "spar_mass_half_kg": _get_scalar("struct.mass.spar_mass_half"),
        "spar_mass_full_kg": _get_scalar("struct.mass.spar_mass_full"),
        "total_mass_full_kg": _get_scalar("struct.mass.total_mass_full"),
        "case_names": case_names,
        "main_t_seg": prob.get_val("struct.seg_mapper.main_t_seg").copy(),
        "main_r_seg": prob.get_val("struct.seg_mapper.main_r_seg").copy(),
        "EI_main_elem": prob.get_val("struct.spar_props.EI_main").copy(),
    }

    if multi_case:
        case_results = {}
        for case_name in case_names:
            case_path = f"struct.case_{case_name}"
            case_res = {
                "failure": _get_scalar(f"{case_path}.failure"),
                "buckling_index": _get_scalar(f"{case_path}.buckling_index"),
                "twist_max_deg": _get_scalar(f"{case_path}.twist_max_deg"),
                "tip_deflection_m": _get_scalar(f"{case_path}.tip_deflection_m"),
                "disp": prob.get_val(f"{case_path}.disp").copy(),
                "vonmises_main": prob.get_val(f"{case_path}.vonmises_main").copy(),
            }
            if rear_on:
                case_res["vonmises_rear"] = prob.get_val(f"{case_path}.vonmises_rear").copy()
            case_results[case_name] = case_res

        res["cases"] = case_results
        res["failure"] = max(case["failure"] for case in case_results.values())
        res["buckling_index"] = max(case["buckling_index"] for case in case_results.values())
        res["twist_max_deg"] = max(case["twist_max_deg"] for case in case_results.values())
        res["tip_deflection_m"] = max(case["tip_deflection_m"] for case in case_results.values())
        res["disp"] = None
        res["vonmises_main"] = None
        if rear_on:
            res["vonmises_rear"] = None
    else:
        res["failure"] = _get_scalar("struct.failure.failure")
        res["buckling_index"] = _get_scalar("struct.buckling.buckling_index")
        res["twist_max_deg"] = _get_scalar("struct.twist.twist_max_deg")
        res["disp"] = prob.get_val("struct.fem.disp").copy()
        res["tip_deflection_m"] = _get_scalar("struct.tip_defl.tip_deflection_m")
        res["vonmises_main"] = prob.get_val("struct.stress.vonmises_main").copy()
        if rear_on:
            res["vonmises_rear"] = prob.get_val("struct.stress.vonmises_rear").copy()

    if rear_on:
        res["rear_t_seg"] = prob.get_val("struct.seg_mapper.rear_t_seg").copy()
        res["rear_r_seg"] = prob.get_val("struct.seg_mapper.rear_r_seg").copy()
        res["EI_rear_elem"] = prob.get_val("struct.spar_props.EI_rear").copy()

    return res
