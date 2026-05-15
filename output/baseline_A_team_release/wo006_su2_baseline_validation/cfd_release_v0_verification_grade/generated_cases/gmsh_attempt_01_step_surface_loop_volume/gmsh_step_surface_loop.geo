SetFactory("OpenCASCADE");
Geometry.OCCSewFaces = 1;
Geometry.Tolerance = 1e-6;
Mesh.Algorithm3D = 10;
Mesh.CharacteristicLengthMin = 20;
Mesh.CharacteristicLengthMax = 1000;
Merge "/Volumes/Samsung SSD/hpa-mdo/output/baseline_A_team_release/wo006_su2_baseline_validation/wo006f_su2_engineering_result/attempt_07_openvsp_gmsh_current_vsp/current_main_wing.step";
s() = Surface "*";
Printf("GMSH_ATTEMPT01 imported_surfaces=%g", #s());
Surface Loop(100) = {s()};
Volume(100) = {100};
Box(200) = {-10000, -20000, -10000, 45000, 40000, 25000};
BooleanDifference{ Volume{200}; Delete; }{ Volume{100}; Delete; }
Physical Surface("farfield") = {57,58,59,60,61,62};
Physical Surface("wing_wall_unclassified") = {s()};
Physical Volume("fluid") = {200};
