{
  pkgs,
  lib,
  config,
  inputs,
  ...
}: {
  packages = with pkgs; [
    gcc
    gccStdenv.cc.cc.lib
    zlib
    just
    # R and the irace package, which the irace binding runs against. The
    # wrapper puts an R on `PATH` that already resolves `library(irace)`.
    (rWrapper.override {packages = with rPackages; [irace];})
  ];

  # The commit gates, split by what they cost. `just check` is the fast subset
  # and runs on every commit; the full set takes about a minute and a half, so
  # it runs before a push instead. The justfile is their one definition, which
  # is also what CI calls.
  git-hooks.hooks = {
    check = {
      enable = true;
      name = "commit gates (fast)";
      entry = "just check";
      pass_filenames = false;
      language = "system";
      stages = ["pre-commit"];
    };
    gates = {
      enable = true;
      name = "commit gates (full)";
      entry = "just gates";
      pass_filenames = false;
      language = "system";
      stages = ["pre-push"];
    };
  };

  enterTest = ''
    just gates
  '';
  languages = {
    python = {
      enable = true;
      package = pkgs.python314;
      uv = {
        enable = true;
        sync.enable = true;
      };
    };
  };

  # rpy2 loads `libR` itself and never runs `R` or `Rscript`, so it reads out
  # of the environment what those launchers would otherwise carry for it.
  # `R_HOME` names the installation it loads from, and `R_LIBS_SITE` is what
  # `library(irace)` resolves against. Absent an `R_HOME`, rpy2 falls back to
  # running `R RHOME`, which needs a launcher on `PATH`: an environment
  # holding the virtualenv alone, which is what an editor configured against
  # the interpreter has, then reaches no R at all.
  #
  # `R_HOME` is the unwrapped R the wrapper above wraps. `R_LIBS_SITE` is
  # asked of the wrapper, which holds the dependency closure inside a
  # compiled launcher and is the one place it need not be restated here.
  env.R_HOME = "${pkgs.R}/lib/R";

  enterShell = ''
    export R_LIBS_SITE="$(R --no-echo -e 'cat(paste(.libPaths(), collapse = ":"))')"
  '';

  # rpy2 publishes no Linux wheel for its compiled half, so it builds from
  # source here and, by default, compiles against R's headers. That would
  # make installing the package depend on R being present, which the gates
  # that never start R would then inherit. Loading `libR` at run time
  # instead keeps the install identical everywhere and leaves R a
  # requirement of running a race rather than of installing the binding.
  env.RPY2_CFFI_MODE = "ABI";

  env.LD_LIBRARY_PATH = with pkgs; lib.makeLibraryPath [
    stdenv.cc.cc.lib
    zlib
  ];
}
