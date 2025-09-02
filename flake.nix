{
  description = "A basic flake for my Python Projects";

  inputs = {
    nixpkgs.url = "github:nixos/nixpkgs?ref=nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
    poetry2nix = {
      url = "github:nix-community/poetry2nix";
      inputs.nixpkgs.follows = "nixpkgs";
    };
  };

  outputs = {
    self,
    nixpkgs,
    flake-utils,
    poetry2nix,
  }: (
    flake-utils.lib.eachDefaultSystem
    (system: let
      pkgs = import nixpkgs {
        inherit system;

        config = {
          allowUnfree = true;
          # cudaSupport = true;
        };
      };

      inherit (poetry2nix.lib.mkPoetry2Nix { inherit pkgs; }) mkPoetryApplication;
    in {
      packages = {
        ragebaiter = mkPoetryApplication {projectDir = ./.;};
        default = self.packages.${system}.ragebaiter;
      };

      apps = {
        # TODO: Add app here
        # default = flake-utils.lib.mkApp {
        #   drv = ...;
        # };
      };

      devShells.default = pkgs.mkShell {
        buildInputs = with pkgs; [
          libopus
          ffmpeg
          triton-llvm
        ];

        shellHook = ''
          export LD_LIBRARY_PATH=${pkgs.libopus}/lib:${pkgs.ffmpeg}/lib:${pkgs.gcc.cc.lib}/lib:$LD_LIBRARY_PATH
        '';
      };
    })
  );
}
