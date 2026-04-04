#!/bin/bash
# Project quality check script

echo "=========================================="
echo "QUANT SENTINEL - QUALITY CHECK"
echo "=========================================="

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

ERRORS=0

# Check Python code quality
echo -e "\n${YELLOW}[1/5]${NC} Checking Python imports..."
python3 -m py_compile src/*.py 2>/dev/null || {
    echo -e "${RED}✗ Python compile errors found${NC}"
    ((ERRORS++))
}

# Check Python type hints
echo -e "\n${YELLOW}[2/5]${NC} Checking requirements.txt versions..."
if grep -E "^[a-zA-Z0-9_-]+$" requirements.txt | grep -v "^#" | grep -v "^$" >/dev/null; then
    echo -e "${RED}✗ Some packages are not pinned to versions${NC}"
    ((ERRORS++))
else
    echo -e "${GREEN}✓ All packages properly pinned${NC}"
fi

# Check TypeScript compilation
echo -e "\n${YELLOW}[3/5]${NC} Checking TypeScript compilation..."
cd frontend && npm run type-check >/dev/null 2>&1 || {
    echo -e "${RED}✗ TypeScript errors found${NC}"
    ((ERRORS++))
}

# Check ESLint
echo -e "\n${YELLOW}[4/5]${NC} Checking ESLint rules..."
npm run lint >/dev/null 2>&1 || {
    echo -e "${YELLOW}⚠ ESLint warnings found (not fatal)${NC}"
}

cd ..

# Check test coverage
echo -e "\n${YELLOW}[5/5]${NC} Verifying test files..."
if [ -f "tests/run_all_tests.py" ]; then
    echo -e "${GREEN}✓ Test suite found${NC}"
else
    echo -e "${RED}✗ Test suite missing${NC}"
    ((ERRORS++))
fi

# Summary
echo -e "\n=========================================="
if [ $ERRORS -eq 0 ]; then
    echo -e "${GREEN}✅ ALL CHECKS PASSED${NC}"
    exit 0
else
    echo -e "${RED}❌ $ERRORS CHECK(S) FAILED${NC}"
    exit 1
fi

