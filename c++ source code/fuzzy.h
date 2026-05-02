#pragma once
#include <string>
#include <vector>
#include <functional>
#include <utility>

namespace fuzzy {

// Raw edit-distance ratio, 0-100
int ratio(const std::string& a, const std::string& b);

// Sort tokens alphabetically before comparing
int token_sort_ratio(const std::string& a, const std::string& b);

// Set-based token comparison (best of intersection/difference combos)
int token_set_ratio(const std::string& a, const std::string& b);

// token_sort_ratio + subset boost:
// if ALL tokens of `a` appear in `b` and `a` has >=2 tokens, lift score to >=85
int subset_sort_ratio(const std::string& a, const std::string& b);

// Return {best_match, score}. Returns {"", 0} if choices is empty.
std::pair<std::string, int> extract_one(
    const std::string& query,
    const std::vector<std::string>& choices,
    std::function<int(const std::string&, const std::string&)> scorer
        = nullptr   // defaults to token_sort_ratio
);

} // namespace fuzzy
