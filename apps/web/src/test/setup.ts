// Testing Library only unmounts after each test on its own when the runner exposes globals; this
// one does not, so every test file starts from an empty document here.
import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

afterEach(cleanup);
