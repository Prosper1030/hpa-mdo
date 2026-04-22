using JSON3
using Xfoil

request_path = ARGS[1]
response_path = ARGS[2]
queries = JSON3.read(read(request_path, String))

results = Any[]
for query in queries
    push!(results, Dict(
        "template_id" => query["template_id"],
        "reynolds" => query["reynolds"],
        "cl_samples" => query["cl_samples"],
        "roughness_mode" => query["roughness_mode"],
        "status" => "stubbed_ok",
        "polar_points" => Any[],
    ))
end

write(response_path, JSON3.write(results))
