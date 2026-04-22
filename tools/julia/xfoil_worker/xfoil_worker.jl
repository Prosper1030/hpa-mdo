using JSON3
using Xfoil


function parse_coordinates(payload)
    x = Float64[]
    y = Float64[]
    for point in payload
        if length(point) != 2
            error("Airfoil coordinate entries must be [x, y] pairs.")
        end
        push!(x, Float64(point[1]))
        push!(y, Float64(point[2]))
    end
    if length(x) < 3
        error("Airfoil coordinates must contain at least three points.")
    end
    return x, y
end


function roughness_controls(mode::AbstractString)
    if mode == "clean"
        return (ncrit = 9.0, xtrip = (1.0, 1.0))
    elseif mode == "dirty" || mode == "rough"
        return (ncrit = 5.0, xtrip = (0.05, 0.05))
    else
        return (ncrit = 7.0, xtrip = (0.30, 0.30))
    end
end


function alpha_grid(cl_samples::Vector{Float64})
    max_abs_cl = isempty(cl_samples) ? 1.0 : maximum(abs.(cl_samples))
    alpha_max = max(10.0, 4.0 + 10.0 * max_abs_cl)
    return collect(-4.0:0.5:alpha_max)
end


function build_polar_points(alpha_deg, cl, cd, cdp, cm, converged, cl_samples)
    converged_indices = findall(converged)
    isempty(converged_indices) && return Any[]

    cl_converged = Float64[Float64(cl[i]) for i in converged_indices]
    points = Any[]
    for cl_target in cl_samples
        best_local_index = argmin(abs.(cl_converged .- cl_target))
        best_index = converged_indices[best_local_index]
        push!(points, Dict(
            "cl_target" => Float64(cl_target),
            "alpha_deg" => Float64(alpha_deg[best_index]),
            "cl" => Float64(cl[best_index]),
            "cd" => Float64(cd[best_index]),
            "cdp" => Float64(cdp[best_index]),
            "cm" => Float64(cm[best_index]),
            "converged" => Bool(converged[best_index]),
            "cl_error" => Float64(cl[best_index] - cl_target),
        ))
    end
    return points
end


function analyze_query(query)
    template_id = String(query["template_id"])
    reynolds = Float64(query["reynolds"])
    roughness_mode = String(query["roughness_mode"])
    geometry_hash = String(query["geometry_hash"])
    cl_samples = Float64[Float64(value) for value in query["cl_samples"]]
    x, y = parse_coordinates(query["coordinates"])
    alpha = alpha_grid(cl_samples)
    controls = roughness_controls(roughness_mode)

    cl, cd, cdp, cm, converged = Xfoil.alpha_sweep(
        x,
        y,
        alpha,
        reynolds;
        mach = 0.0,
        iter = 60,
        npan = 120,
        reinit = false,
        percussive_maintenance = true,
        printdata = false,
        zeroinit = true,
        clmaxstop = false,
        clminstop = false,
        ncrit = controls.ncrit,
        xtrip = controls.xtrip,
    )

    polar_points = build_polar_points(alpha, cl, cd, cdp, cm, converged, cl_samples)
    status = isempty(polar_points) ? "analysis_failed" : "ok"

    return Dict(
        "template_id" => template_id,
        "reynolds" => reynolds,
        "cl_samples" => cl_samples,
        "roughness_mode" => roughness_mode,
        "geometry_hash" => geometry_hash,
        "status" => status,
        "polar_points" => polar_points,
    )
end


request_path = ARGS[1]
response_path = ARGS[2]
queries = JSON3.read(read(request_path, String))

results = Any[]
for query in queries
    push!(results, analyze_query(query))
end

write(response_path, JSON3.write(results))
