#include "llama.h"

#include <cstdio>
#include <cstdlib>
#include <iostream>
#include <iterator>
#include <memory>
#include <string>
#include <sys/resource.h>
#include <vector>

static bool decode(llama_context * context, llama_batch_ext * batch, const llama_token * tokens, int count, int position) {
    llama_batch_ext_clear(batch);
    for (int i = 0; i < count; ++i) {
        const int index = llama_batch_ext_add_token(batch, 0, tokens[i]);
        const llama_pos token_position = position + i;
        llama_batch_ext_set_pos(batch, index, &token_position);
    }
    llama_batch_ext_set_output_logits(batch, count - 1, true);
    return llama_process(context, LLAMA_PROCESS_TYPE_DECODE, batch) == 0;
}

int main(int argc, char ** argv) {
    if (argc != 5) {
        std::fprintf(stderr, "usage: mobile-inference-bench GGUF THREADS GPU_LAYERS REQUESTS < prompt\n");
        return 2;
    }
    const int threads = std::atoi(argv[2]);
    const int gpu_layers = std::atoi(argv[3]);
    const int requests = std::atoi(argv[4]);
    if (threads < 0 || gpu_layers < 0 || requests < 1) return 2;
    const std::string prompt(std::istreambuf_iterator<char>(std::cin), {});
    const int64_t start = ggml_time_us();
    llama_backend_init();
    auto model_params = llama_model_default_params();
    model_params.n_gpu_layers = gpu_layers;
    std::unique_ptr<llama_model, decltype(&llama_model_free)> model(
        llama_model_load_from_file(argv[1], model_params), llama_model_free);
    if (!model) return 1;
    const int64_t loaded = ggml_time_us();

    const llama_vocab * vocabulary = llama_model_get_vocab(model.get());
    const int prompt_size = -llama_tokenize(vocabulary, prompt.data(), prompt.size(), nullptr, 0, true, true);
    if (prompt_size < 1) return 1;
    std::vector<llama_token> tokens(prompt_size);
    if (llama_tokenize(vocabulary, prompt.data(), prompt.size(), tokens.data(), tokens.size(), true, true) != prompt_size) return 1;

    constexpr int max_new_tokens = 64;
    auto params = llama_context_default_params();
    if (threads > 0) {
        params.n_threads = threads;
        params.n_threads_batch = threads;
    }
    params.n_ctx = prompt_size + max_new_tokens - 1;
    params.n_batch = prompt_size;
    std::unique_ptr<llama_context, decltype(&llama_free)> context(llama_init_from_model(model.get(), params), llama_free);
    if (!context) return 1;
    std::unique_ptr<llama_sampler, decltype(&llama_sampler_free)> sampler(
        llama_sampler_init_greedy(), llama_sampler_free);
    std::unique_ptr<llama_batch_ext, decltype(&llama_batch_ext_free)> batch(
        llama_batch_ext_init(context.get()), llama_batch_ext_free);
    const int64_t initialized = ggml_time_us();
    std::printf("SETUP\t%d\t%d\t%lld\t%lld\n", llama_n_threads(context.get()), llama_n_threads_batch(context.get()),
        static_cast<long long>(loaded - start), static_cast<long long>(initialized - loaded));
    for (int request = 0; request < requests; ++request) {
        const int64_t requested = ggml_time_us();
        llama_memory_clear(llama_get_memory(context.get()), false);
        llama_sampler_reset(sampler.get());
        if (!decode(context.get(), batch.get(), tokens.data(), tokens.size(), 0)) return 1;
        llama_synchronize(context.get());
        const int64_t prefilled = ggml_time_us();

        std::string answer;
        int generated = 0;
        for (; generated < max_new_tokens; ++generated) {
            llama_token token = llama_sampler_sample(sampler.get(), context.get(), -1);
            if (llama_vocab_is_eog(vocabulary, token)) break;
            char piece[128];
            const int size = llama_token_to_piece(vocabulary, token, piece, sizeof(piece), 0, true);
            if (size < 0) return 1;
            answer.append(piece, size);
            if (generated + 1 < max_new_tokens &&
                !decode(context.get(), batch.get(), &token, 1, prompt_size + generated)) return 1;
        }
        const int64_t completed = ggml_time_us();
        std::printf("REQUEST\t%d\t%lld\t%lld\t%lld\t%d\t", request,
            static_cast<long long>(completed - requested), static_cast<long long>(prefilled - requested),
            static_cast<long long>(completed - prefilled), generated);
        for (unsigned char byte : answer) std::printf("%02x", static_cast<unsigned int>(byte));
        std::printf("\n");
        std::fflush(stdout);
    }
    rusage usage{};
    if (getrusage(RUSAGE_SELF, &usage) == 0) std::printf("RSS\t%ld\n", usage.ru_maxrss);
}
