#include "fuzzy.h"
#include <algorithm>
#include <sstream>
#include <set>
#include <cmath>

namespace fuzzy {

// ── Levenshtein edit distance ─────────────────────────────────────────────────

static int levenshtein(const std::string& a, const std::string& b) {
    int m = (int)a.size(), n = (int)b.size();
    std::vector<int> prev(n + 1), curr(n + 1);
    for (int j = 0; j <= n; ++j) prev[j] = j;
    for (int i = 1; i <= m; ++i) {
        curr[0] = i;
        for (int j = 1; j <= n; ++j) {
            if (a[i-1] == b[j-1])
                curr[j] = prev[j-1];
            else
                curr[j] = 1 + std::min({prev[j], curr[j-1], prev[j-1]});
        }
        std::swap(prev, curr);
    }
    return prev[n];
}

// ── Token helpers ─────────────────────────────────────────────────────────────

static std::vector<std::string> tokenize(const std::string& s) {
    std::istringstream iss(s);
    std::vector<std::string> tokens;
    std::string tok;
    while (iss >> tok) tokens.push_back(tok);
    return tokens;
}

static std::string sorted_tokens_join(const std::string& s) {
    auto toks = tokenize(s);
    std::sort(toks.begin(), toks.end());
    std::string out;
    for (auto& t : toks) {
        if (!out.empty()) out += ' ';
        out += t;
    }
    return out;
}

static std::string join(const std::vector<std::string>& v) {
    std::string out;
    for (auto& s : v) {
        if (!out.empty()) out += ' ';
        out += s;
    }
    return out;
}

// ── Public API ────────────────────────────────────────────────────────────────

int ratio(const std::string& a, const std::string& b) {
    if (a.empty() && b.empty()) return 100;
    int total = (int)(a.size() + b.size());
    if (total == 0) return 100;
    int dist = levenshtein(a, b);
    // 2*matching / total; matching ≈ (total - dist) / 2 for pure substitutions
    // Direct Levenshtein ratio: (total - dist) / total * 100
    return (int)(100.0 * (total - dist) / total);
}

int token_sort_ratio(const std::string& a, const std::string& b) {
    return ratio(sorted_tokens_join(a), sorted_tokens_join(b));
}

int token_set_ratio(const std::string& a, const std::string& b) {
    auto ta_vec = tokenize(a);
    auto tb_vec = tokenize(b);
    std::set<std::string> ta(ta_vec.begin(), ta_vec.end());
    std::set<std::string> tb(tb_vec.begin(), tb_vec.end());

    std::vector<std::string> intersect, only_a, only_b;
    std::set_intersection(ta.begin(), ta.end(), tb.begin(), tb.end(),
                          std::back_inserter(intersect));
    std::set_difference(ta.begin(), ta.end(), tb.begin(), tb.end(),
                        std::back_inserter(only_a));
    std::set_difference(tb.begin(), tb.end(), ta.begin(), ta.end(),
                        std::back_inserter(only_b));

    std::string s_i  = join(intersect);
    std::string s_ia = s_i + (only_a.empty() ? "" : " " + join(only_a));
    std::string s_ib = s_i + (only_b.empty() ? "" : " " + join(only_b));

    int r1 = ratio(s_i,  s_ia);
    int r2 = ratio(s_i,  s_ib);
    int r3 = ratio(s_ia, s_ib);
    return std::max({r1, r2, r3});
}

int subset_sort_ratio(const std::string& a, const std::string& b) {
    int base = token_sort_ratio(a, b);

    auto ta = tokenize(a);
    auto tb = tokenize(b);
    if ((int)ta.size() >= 2) {
        std::set<std::string> sa(ta.begin(), ta.end());
        std::set<std::string> sb(tb.begin(), tb.end());
        bool is_subset = std::includes(sb.begin(), sb.end(), sa.begin(), sa.end());
        if (is_subset) base = std::max(base, 85);
    }
    return base;
}

std::pair<std::string, int> extract_one(
    const std::string& query,
    const std::vector<std::string>& choices,
    std::function<int(const std::string&, const std::string&)> scorer)
{
    if (choices.empty()) return {"", 0};
    if (!scorer) scorer = token_sort_ratio;

    std::string best_match;
    int best_score = -1;
    for (auto& c : choices) {
        int s = scorer(query, c);
        if (s > best_score) {
            best_score = s;
            best_match = c;
        }
    }
    return {best_match, best_score};
}

} // namespace fuzzy
