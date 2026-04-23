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
    alpha_max = min(18.0, max(12.0, 5.0 + 14.0 * max_abs_cl))
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


function build_sweep_summary(alpha_deg, cl, cd, cdp, cm, converged)
    alpha_count = length(alpha_deg)
    converged_indices = findall(converged)
    alpha_step_deg = alpha_count <= 1 ? 0.0 : Float64(alpha_deg[2] - alpha_deg[1])
    summary = Dict(
        "sweep_point_count" => Int(alpha_count),
        "converged_point_count" => Int(length(converged_indices)),
        "alpha_min_deg" => alpha_count == 0 ? nothing : Float64(alpha_deg[1]),
        "alpha_max_deg" => alpha_count == 0 ? nothing : Float64(alpha_deg[end]),
        "alpha_step_deg" => alpha_step_deg,
        "usable_polar_points" => !isempty(converged_indices),
        "cl_max_observed" => nothing,
        "alpha_at_cl_max_deg" => nothing,
        "last_converged_alpha_deg" => nothing,
        "clmax_is_lower_bound" => false,
        "first_pass_observed_clmax_proxy" => nothing,
        "first_pass_observed_clmax_proxy_alpha_deg" => nothing,
        "first_pass_observed_clmax_proxy_cd" => nothing,
        "first_pass_observed_clmax_proxy_cdp" => nothing,
        "first_pass_observed_clmax_proxy_cm" => nothing,
        "first_pass_observed_clmax_proxy_index" => nothing,
        "first_pass_observed_clmax_proxy_at_sweep_edge" => nothing,
    )

    if isempty(converged_indices)
        return summary
    end

    cl_converged = Float64[Float64(cl[i]) for i in converged_indices]
    observed_local_index = argmax(cl_converged)
    observed_index = converged_indices[observed_local_index]
    last_converged_index = converged_indices[end]
    summary["cl_max_observed"] = Float64(cl[observed_index])
    summary["alpha_at_cl_max_deg"] = Float64(alpha_deg[observed_index])
    summary["last_converged_alpha_deg"] = Float64(alpha_deg[last_converged_index])
    summary["clmax_is_lower_bound"] = Bool(observed_index == last_converged_index)
    summary["first_pass_observed_clmax_proxy"] = Float64(cl[observed_index])
    summary["first_pass_observed_clmax_proxy_alpha_deg"] = Float64(alpha_deg[observed_index])
    summary["first_pass_observed_clmax_proxy_cd"] = Float64(cd[observed_index])
    summary["first_pass_observed_clmax_proxy_cdp"] = Float64(cdp[observed_index])
    summary["first_pass_observed_clmax_proxy_cm"] = Float64(cm[observed_index])
    summary["first_pass_observed_clmax_proxy_index"] = Int(observed_index)
    summary["first_pass_observed_clmax_proxy_at_sweep_edge"] =
        Bool(observed_index == firstindex(alpha_deg) || observed_index == lastindex(alpha_deg))
    return summary
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
    sweep_summary = build_sweep_summary(alpha, cl, cd, cdp, cm, converged)
    status = isempty(polar_points) ? "analysis_failed" : "ok"

    return Dict(
        "template_id" => template_id,
        "reynolds" => reynolds,
        "cl_samples" => cl_samples,
        "roughness_mode" => roughness_mode,
        "geometry_hash" => geometry_hash,
        "status" => status,
        "polar_points" => polar_points,
        "sweep_summary" => sweep_summary,
    )
end


function analyze_queries(queries)
    results = Any[]
    for query in queries
        push!(results, analyze_query(query))
    end
    return results
end


if length(ARGS) == 1 && ARGS[1] == "--stdio"
    while !eof(stdin)
        line = try
            readline(stdin)
        catch
            break
        end
        isempty(strip(line)) && continue

        payload = JSON3.read(line)
        if payload isa AbstractDict && get(payload, "command", nothing) == "shutdown"
            break
        end

        results = analyze_queries(payload)
        write(stdout, JSON3.write(results))
        write(stdout, "\n")
        flush(stdout)
    end
elseif length(ARGS) == 2
    request_path = ARGS[1]
    response_path = ARGS[2]
    queries = JSON3.read(read(request_path, String))
    write(response_path, JSON3.write(analyze_queries(queries)))
else
    error("Usage: xfoil_worker.jl <request.json> <response.json> OR xfoil_worker.jl --stdio")
end
