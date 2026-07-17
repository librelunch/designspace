{
  inputs = {
    nixpkgs.url = "github:nixos/nixpkgs/nixos-unstable";
    devenv.url = "github:cachix/devenv";
    nixpkgs-python.url = "github:cachix/nixpkgs-python";
    nixpkgs-python.inputs.nixpkgs.follows = "nixpkgs";
  };

  outputs = {
    self,
    nixpkgs,
    devenv,
    ...
  } @ inputs: let
    system = "x86_64-linux";
    pkgs = import nixpkgs {
      inherit system;
      config.allowUnfree = true;
    };
  in {
    # If you need native CUDA support (doesn't apply to packages like PyTorch which bundle their own CUDA):
    # nixpkgs.config.cudaSupport = true;

    devShells.${system}.default = devenv.lib.mkShell {
      inherit inputs pkgs;
      modules = [(import ./devenv.nix)];
    };
  };
}
