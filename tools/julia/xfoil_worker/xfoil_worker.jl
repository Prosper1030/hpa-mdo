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


function screening_alpha_grid(cl_target::Float64)
    alpha_hint = clamp(8.0 * cl_target - 3.0, -4.0, 12.0)
    coarse_grid = [
        -4.0,
        -1.0,
        alpha_hint - 2.0,
        alpha_hint,
        alpha_hint + 2.0,
        5.0,
        8.0,
        11.0,
        14.0,
    ]
    return sort(unique(Float64[clamp(alpha, -6.0, 18.0) for alpha in coarse_grid]))
end


function alpha_grid(cl_samples::Vector{Float64})
    max_abs_cl = isempty(cl_samples) ? 1.0 : maximum(abs.(cl_samples))
    alpha_max = min(18.0, max(12.0, 5.0 + 14.0 * max_abs_cl))
    return collect(-4.0:0.5:alpha_max)
end


function initialize_airfoil!(x, y; npan::Int)
    Xfoil.set_coordinates(x, y)
    Xfoil.pane(npan = npan)
end


function screening_point(alpha_deg::Float64, cl_target::Float64, cl, cd, cdp, cm, converged::Bool)
    return Dict(
        "cl_target" => Float64(cl_target),
        "alpha_deg" => Float64(alpha_deg),
        "cl" => Float64(cl),
        "cd" => Float64(cd),
        "cdp" => Float64(cdp),
        "cm" => Float64(cm),
        "converged" => Bool(converged),
        "cl_error" => Float64(cl - cl_target),
    )
end


function solve_screening_alpha(alpha_deg::Float64, reynolds::Float64; mach, iter, ncrit, xtrip, reinit::Bool)
    try
        cl, cd, cdp, cm, converged = Xfoil.solve_alpha(
            alpha_deg,
            reynolds;
            mach = mach,
            iter = iter,
            ncrit = ncrit,
            reinit = reinit,
            xtrip = xtrip,
        )
        return Dict(
            "alpha_deg" => Float64(alpha_deg),
            "cl" => Float64(cl),
            "cd" => Float64(cd),
            "cdp" => Float64(cdp),
            "cm" => Float64(cm),
            "converged" => Bool(converged),
        )
    catch exc
        return Dict(
            "alpha_deg" => Float64(alpha_deg),
            "cl" => NaN,
            "cd" => NaN,
            "cdp" => NaN,
            "cm" => NaN,
            "converged" => false,
            "error" => sprint(showerror, exc),
        )
    end
end


function bracket_target_cl(points, cl_target::Float64)
    converged_points = sort(
        [point for point in points if Bool(get(point, "converged", false))],
        by = point -> Float64(point["alpha_deg"]),
    )
    if length(converged_points) < 2
        return nothing
    end

    for index in 1:(length(converged_points) - 1)
        low = converged_points[index]
        high = converged_points[index + 1]
        cl_low = Float64(low["cl"])
        cl_high = Float64(high["cl"])
        if (cl_low - cl_target) * (cl_high - cl_target) <= 0.0
            return low, high
        end
    end

    return nothing
end


function guarded_secant_alpha(low, high, cl_target::Float64)
    alpha_low = Float64(low["alpha_deg"])
    alpha_high = Float64(high["alpha_deg"])
    cl_low = Float64(low["cl"])
    cl_high = Float64(high["cl"])

    if abs(cl_high - cl_low) < 1.0e-9
        return 0.5 * (alpha_low + alpha_high)
    end

    alpha_candidate = alpha_low + (cl_target - cl_low) * (alpha_high - alpha_low) / (cl_high - cl_low)
    lower_bound = min(alpha_low, alpha_high)
    upper_bound = max(alpha_low, alpha_high)
    if !isfinite(alpha_candidate) || alpha_candidate <= lower_bound || alpha_candidate >= upper_bound
        return 0.5 * (alpha_low + alpha_high)
    end
    return alpha_candidate
end


function best_converged_point(points, cl_target::Float64; prefer_below_target::Bool)
    converged_points = [point for point in points if Bool(get(point, "converged", false))]
    isempty(converged_points) && return nothing

    candidate_pool = converged_points
    if prefer_below_target
        below_target = [point for point in converged_points if Float64(point["cl"]) <= cl_target]
        if !isempty(below_target)
            candidate_pool = below_target
        end
    end

    best_index = argmin([abs(Float64(point["cl"]) - cl_target) for point in candidate_pool])
    return candidate_pool[best_index]
end


function mini_sweep_alphas(center_alpha_deg::Float64)
    offsets = (-1.0, -0.5, 0.0, 0.5, 1.0)
    return sort(unique(Float64[clamp(center_alpha_deg + offset, -6.0, 18.0) for offset in offsets]))
end


function screening_summary(points, target_points, requested_count::Int, fallback_used::Bool)
    alpha_values = [Float64(point["alpha_deg"]) for point in points]
    converged_points = [point for point in points if Bool(get(point, "converged", false))]
    converged_alphas = [Float64(point["alpha_deg"]) for point in converged_points]

    cl_max_observed = nothing
    alpha_at_cl_max_deg = nothing
    if !isempty(converged_points)
        best_index = argmax([Float64(point["cl"]) for point in converged_points])
        best_point = converged_points[best_index]
        cl_max_observed = Float64(best_point["cl"])
        alpha_at_cl_max_deg = Float64(best_point["alpha_deg"])
    end

    return Dict(
        "target_cl_requested_count" => Int(requested_count),
        "target_cl_converged_count" => Int(
            count(point -> Bool(get(point, "target_cl_converged", false)), target_points)
        ),
        "fallback_used" => Bool(fallback_used),
        "mini_sweep_fallback_count" => Int(
            count(point -> Bool(get(point, "fallback_used", false)), target_points)
        ),
        "screening_point_count" => Int(length(points)),
        "sweep_point_count" => Int(length(points)),
        "converged_point_count" => Int(length(converged_points)),
        "alpha_min_deg" => isempty(alpha_values) ? nothing : minimum(alpha_values),
        "alpha_max_deg" => isempty(alpha_values) ? nothing : maximum(alpha_values),
        "alpha_step_deg" => nothing,
        "usable_polar_points" => !isempty(target_points),
        "cl_max_observed" => cl_max_observed,
        "alpha_at_cl_max_deg" => alpha_at_cl_max_deg,
        "last_converged_alpha_deg" => isempty(converged_alphas) ? nothing : maximum(converged_alphas),
        "clmax_is_lower_bound" => true,
        "first_pass_observed_clmax_proxy" => cl_max_observed,
        "first_pass_observed_clmax_proxy_alpha_deg" => alpha_at_cl_max_deg,
        "first_pass_observed_clmax_proxy_cd" => nothing,
        "first_pass_observed_clmax_proxy_cdp" => nothing,
        "first_pass_observed_clmax_proxy_cm" => nothing,
        "first_pass_observed_clmax_proxy_index" => nothing,
        "first_pass_observed_clmax_proxy_at_sweep_edge" => false,
    )
end


function shared_coarse_alpha_grid(cl_targets::Vector{Float64})
    union = Set{Float64}()
    for cl_target in cl_targets
        for alpha in screening_alpha_grid(cl_target)
            push!(union, round(alpha; digits = 4))
        end
    end
    return sort(collect(union))
end


function run_alpha_pass(alphas::Vector{Float64}, reynolds::Float64; mach, iter, ncrit, xtrip)
    points = Any[]
    previous_converged = true
    for (index, alpha_deg) in enumerate(alphas)
        point = solve_screening_alpha(
            alpha_deg,
            reynolds;
            mach = mach,
            iter = iter,
            ncrit = ncrit,
            xtrip = xtrip,
            reinit = index == 1 || !previous_converged,
        )
        push!(points, point)
        previous_converged = Bool(point["converged"])
    end
    return points
end


function refine_target_cl_from_coarse(
    coarse_points::Vector{Any},
    cl_target::Float64,
    reynolds::Float64;
    mach,
    iter,
    ncrit,
    xtrip,
)
    bracket = bracket_target_cl(coarse_points, cl_target)
    secant_points = Any[]
    best_point = best_converged_point(coarse_points, cl_target; prefer_below_target = false)

    if bracket !== nothing
        low, high = bracket
        for _ in 1:6
            alpha_candidate = guarded_secant_alpha(low, high, cl_target)
            point = solve_screening_alpha(
                alpha_candidate,
                reynolds;
                mach = mach,
                iter = iter,
                ncrit = ncrit,
                xtrip = xtrip,
                reinit = false,
            )
            push!(secant_points, point)
            if Bool(point["converged"])
                if best_point === nothing || abs(Float64(point["cl"]) - cl_target) < abs(Float64(best_point["cl"]) - cl_target)
                    best_point = point
                end
                new_bracket = bracket_target_cl(vcat([low, high], [point]), cl_target)
                if new_bracket !== nothing
                    low, high = new_bracket
                end
                if abs(Float64(point["cl"]) - cl_target) <= 0.015
                    target_result = screening_point(
                        Float64(point["alpha_deg"]),
                        cl_target,
                        Float64(point["cl"]),
                        Float64(point["cd"]),
                        Float64(point["cdp"]),
                        Float64(point["cm"]),
                        true,
                    )
                    target_result["target_cl_converged"] = true
                    target_result["fallback_used"] = false
                    return target_result, secant_points, false
                end
            else
                break
            end
        end
    end

    return nothing, secant_points, true
end


function solve_target_cl_batch(
    x,
    y,
    cl_targets::Vector{Float64},
    reynolds::Float64;
    mach,
    iter,
    npan,
    ncrit,
    xtrip,
)
    initialize_airfoil!(x, y; npan = npan)

    shared_alphas = shared_coarse_alpha_grid(cl_targets)
    coarse_points = run_alpha_pass(
        shared_alphas,
        reynolds;
        mach = mach,
        iter = iter,
        ncrit = ncrit,
        xtrip = xtrip,
    )

    target_points = Any[]
    extra_evaluated = Any[]
    needs_fallback_targets = Float64[]

    for cl_target in cl_targets
        target_result, secant_points, needs_fallback = refine_target_cl_from_coarse(
            convert(Vector{Any}, coarse_points),
            cl_target,
            reynolds;
            mach = mach,
            iter = iter,
            ncrit = ncrit,
            xtrip = xtrip,
        )
        append!(extra_evaluated, secant_points)
        if target_result !== nothing
            push!(target_points, target_result)
        elseif needs_fallback
            push!(needs_fallback_targets, cl_target)
        end
    end

    if !isempty(needs_fallback_targets)
        for cl_target in needs_fallback_targets
            best_point = best_converged_point(
                convert(Vector{Any}, vcat(coarse_points, extra_evaluated)),
                cl_target;
                prefer_below_target = false,
            )
            fallback_center = if best_point === nothing
                first(shared_alphas)
            else
                Float64(best_point["alpha_deg"])
            end
            fallback_alphas = mini_sweep_alphas(fallback_center)
            initialize_airfoil!(x, y; npan = npan)
            fallback_points = run_alpha_pass(
                fallback_alphas,
                reynolds;
                mach = mach,
                iter = iter,
                ncrit = ncrit,
                xtrip = xtrip,
            )
            append!(extra_evaluated, fallback_points)

            fallback_best = best_converged_point(
                convert(Vector{Any}, vcat(coarse_points, extra_evaluated)),
                cl_target;
                prefer_below_target = true,
            )
            if fallback_best === nothing
                continue
            end

            fallback_result = screening_point(
                Float64(fallback_best["alpha_deg"]),
                cl_target,
                Float64(fallback_best["cl"]),
                Float64(fallback_best["cd"]),
                Float64(fallback_best["cdp"]),
                Float64(fallback_best["cm"]),
                true,
            )
            fallback_result["target_cl_converged"] = false
            fallback_result["fallback_used"] = true
            fallback_result["clmax_is_lower_bound"] = true
            push!(target_points, fallback_result)
        end
    end

    fallback_used = any(point -> Bool(get(point, "fallback_used", false)), target_points)
    return target_points, vcat(coarse_points, extra_evaluated), fallback_used
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


function analyze_query_target_cl(query)
    template_id = String(query["template_id"])
    reynolds = Float64(query["reynolds"])
    roughness_mode = String(query["roughness_mode"])
    geometry_hash = String(query["geometry_hash"])
    cl_samples = Float64[Float64(value) for value in query["cl_samples"]]
    analysis_mode = String(get(query, "analysis_mode", "screening_target_cl"))
    analysis_stage = String(get(query, "analysis_stage", "screening"))
    xfoil_max_iter = Int(get(query, "xfoil_max_iter", 60))
    xfoil_panel_count = Int(get(query, "xfoil_panel_count", 120))
    x, y = parse_coordinates(query["coordinates"])
    controls = roughness_controls(roughness_mode)

    target_points, evaluated_points, fallback_used = solve_target_cl_batch(
        x,
        y,
        cl_samples,
        reynolds;
        mach = 0.0,
        iter = xfoil_max_iter,
        npan = xfoil_panel_count,
        ncrit = controls.ncrit,
        xtrip = controls.xtrip,
    )

    screening_result_summary = screening_summary(
        evaluated_points,
        target_points,
        length(cl_samples),
        fallback_used,
    )
    status = isempty(target_points) ? "analysis_failed" : (fallback_used ? "mini_sweep_fallback" : "ok")

    return Dict(
        "template_id" => template_id,
        "reynolds" => reynolds,
        "cl_samples" => cl_samples,
        "roughness_mode" => roughness_mode,
        "geometry_hash" => geometry_hash,
        "analysis_mode" => analysis_mode,
        "analysis_stage" => analysis_stage,
        "status" => status,
        "polar_points" => target_points,
        "screening_summary" => screening_result_summary,
        "sweep_summary" => screening_result_summary,
    )
end


function analyze_query_full_sweep(query)
    template_id = String(query["template_id"])
    reynolds = Float64(query["reynolds"])
    roughness_mode = String(query["roughness_mode"])
    geometry_hash = String(query["geometry_hash"])
    cl_samples = Float64[Float64(value) for value in query["cl_samples"]]
    analysis_mode = String(get(query, "analysis_mode", "full_alpha_sweep"))
    analysis_stage = String(get(query, "analysis_stage", "screening"))
    xfoil_max_iter = Int(get(query, "xfoil_max_iter", 60))
    xfoil_panel_count = Int(get(query, "xfoil_panel_count", 120))
    x, y = parse_coordinates(query["coordinates"])
    alpha = alpha_grid(cl_samples)
    controls = roughness_controls(roughness_mode)

    cl, cd, cdp, cm, converged = Xfoil.alpha_sweep(
        x,
        y,
        alpha,
        reynolds;
        mach = 0.0,
        iter = xfoil_max_iter,
        npan = xfoil_panel_count,
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
        "analysis_mode" => analysis_mode,
        "analysis_stage" => analysis_stage,
        "status" => status,
        "polar_points" => polar_points,
        "sweep_summary" => sweep_summary,
    )
end


function analyze_query(query)
    analysis_mode = String(get(query, "analysis_mode", "full_alpha_sweep"))
    if analysis_mode == "screening_target_cl"
        return analyze_query_target_cl(query)
    elseif analysis_mode == "full_alpha_sweep"
        return analyze_query_full_sweep(query)
    end

    error("Unsupported analysis_mode: " * analysis_mode)
end


function analyze_queries(queries)
    results = Any[]
    for query in queries
        push!(results, analyze_query(query))
    end
    return results
end


function handle_stdio_payload(payload)
    if payload isa AbstractDict && get(payload, "command", nothing) == "shutdown"
        return nothing
    end
    return analyze_queries(payload)
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
        results = handle_stdio_payload(payload)
        results === nothing && break

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
