
CC=clang
CXX=clang++
# no FC for clang
FC=
flags = -O3 -fstrict-aliasing -march=native
vecflags = -fvectorize -fslp-vectorize
novecflags = -fno-vectorize -fno-slp-vectorize
omp_flags=-fopenmp=libomp

ifdef VEC_REPORT
vecflags+=-foptimization-record-file=$@$(SUFFIX).opt.yml
#vecflags+=-mllvm -debug-only=loop-vectorize
#vecflags+=-Rpass-analysis=loop-vectorize
endif

ieee_math_flags+=
fast_math_flags+=-ffast-math

ifdef PRECISE_MATH
$(warning No 'precise' math flags for clang!)
endif

